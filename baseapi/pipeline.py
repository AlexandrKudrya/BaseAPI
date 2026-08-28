"""The request executor: coercion -> checks -> query -> mapping -> response.

Deliberately free of HTTP. ``handle`` takes an endpoint, a database stand-in
and a request, and returns a ``(status, body)`` pair. It never raises
``ApiError``; the only exception that may propagate is ``ConfigError`` for an
unregistered hook, which is a wiring bug rather than a request failure.
"""

from baseapi import mapping
from baseapi.auth import ANONYMOUS
from baseapi.errors import ApiError, ConfigError

_TRUE_STRINGS = ("true", "1", "yes", "on")
_FALSE_STRINGS = ("false", "0", "no", "off")


def _error(status, message):
    return status, {"error": {"code": status, "message": message}}


def _read_source(location, name, path, query, body, headers, auth):
    if location == "path":
        return path.get(name)
    if location == "query":
        return query.get(name)
    if location == "body":
        return body.get(name)
    if location == "auth":
        return auth.get(name)
    if location == "header":
        target = name.lower().replace("_", "-")
        for key, value in headers.items():
            if key.lower().replace("_", "-") == target:
                return value
        return None
    return None


def _coerce(name, type_name, value):
    if type_name == "int":
        if isinstance(value, bool):
            raise ApiError(422, "cannot coerce parameter %r to int" % name)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                raise ApiError(422, "cannot coerce parameter %r to int" % name)
        raise ApiError(422, "cannot coerce parameter %r to int" % name)

    if type_name == "float":
        if isinstance(value, bool):
            raise ApiError(422, "cannot coerce parameter %r to float" % name)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                raise ApiError(422, "cannot coerce parameter %r to float" % name)
        raise ApiError(422, "cannot coerce parameter %r to float" % name)

    if type_name == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value == 1:
                return True
            if value == 0:
                return False
            raise ApiError(422, "cannot coerce parameter %r to bool" % name)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in _TRUE_STRINGS:
                return True
            if normalized in _FALSE_STRINGS:
                return False
        raise ApiError(422, "cannot coerce parameter %r to bool" % name)

    if type_name == "str":
        if isinstance(value, bool):
            raise ApiError(422, "cannot coerce parameter %r to str" % name)
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        raise ApiError(422, "cannot coerce parameter %r to str" % name)

    raise ApiError(422, "cannot coerce parameter %r" % name)


def coerce_params(endpoint, *, path=None, query=None, body=None, headers=None,
                  auth=None):
    """Coerce every declared parameter from its declared location."""
    path = path or {}
    query = query or {}
    headers = headers or {}
    if auth is None:
        auth = {}

    body_conf = body
    if any(s.location == "body" for s in endpoint.params.values()) and \
            not isinstance(body_conf, dict):
        raise ApiError(422, "body must be a JSON object")
    body = body_conf if isinstance(body_conf, dict) else {}

    result = {}
    for name, spec in endpoint.params.items():
        raw = _read_source(spec.location, name, path, query, body, headers,
                           auth)
        if raw is None:
            if spec.required:
                raise ApiError(422, "missing required parameter %r" % name)
            if spec.has_default:
                result[name] = spec.default
            continue
        result[name] = _coerce(name, spec.type, raw)
    return result


def handle(endpoint, *, db, path=None, query=None, body=None, auth=None,
           hooks=None):
    """Run one endpoint against one request and return a (status, body) pair."""
    if hooks is None:
        hooks = {}
    if auth is None:
        auth = ANONYMOUS

    # 1. Authentication, before anything else.
    if endpoint.auth == "required" and auth.get("subject") is None:
        return _error(401, "authentication required")

    # 2. Coercion.
    try:
        params = coerce_params(endpoint, path=path, query=query, body=body,
                               auth=auth)
    except ApiError as exc:
        return _error(exc.status, exc.message)

    # 3. Business checks, in file order.
    context = {"params": params, "auth": auth}
    for check in endpoint.checks:
        if check.hook is not None:
            hooked = hooks.get(check.hook)
            if hooked is None:
                raise ConfigError(
                    "hook reference %r is not registered" % check.hook
                )
            passed = bool(hooked(context))
        else:
            passed = bool(check.expression(context))
        if not passed:
            return _error(check.status, check.message)

    # 4. The query.
    result = db.run(endpoint.query.sql, params)
    returns = endpoint.query.returns
    if returns == "one":
        rows = result.rows
        if not rows:
            return _error(endpoint.response.when_empty, "not found")
        row = rows[0]
        context["row"] = row
        context["rows"] = rows
    else:
        context["row"] = None
        context["rows"] = result.rows
    context["result"] = {"rowcount": result.rowcount}

    # 5. Response mapping, then the optional transform hook.
    body_value = mapping.build_body(endpoint.response.fields, context, returns)
    if endpoint.response.transform is not None:
        transform = hooks.get(endpoint.response.transform)
        if transform is None:
            raise ConfigError(
                "transform reference %r is not registered"
                % endpoint.response.transform
            )
        body_value = transform(body_value, context)

    return endpoint.response.status, body_value
