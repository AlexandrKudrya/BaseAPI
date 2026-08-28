"""Validation of ``app.yml`` and ``endpoints/*.yml``.

Everything raised here is a ``ConfigError`` — a config file is wrong, so the
problem is reported at load time. No database connection is opened here.
"""

import os
import re
from dataclasses import dataclass, field

import yaml

from baseapi import dialect, expr
from baseapi.errors import ConfigError

_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PARAM_LOCATIONS = ("path", "query", "body", "header", "auth")
_PARAM_TYPES = ("str", "int", "float", "bool")
_RETURNS_MODES = ("one", "many", "none")


@dataclass
class ParamSpec:
    name: str
    location: str
    type: str
    required: bool = False
    default: object = None
    has_default: bool = False


@dataclass
class CheckSpec:
    expression: object = None
    hook: str = None
    status: int = 400
    message: str = "check failed"


@dataclass
class QuerySpec:
    sql: str
    returns: str


@dataclass
class ResponseSpec:
    status: int = 200
    when_empty: int = 404
    transform: str = None
    fields: object = None


@dataclass
class Endpoint:
    name: str
    method: str
    path: str
    summary: str = ""
    auth: str = "none"
    params: dict = field(default_factory=dict)
    checks: list = field(default_factory=list)
    query: QuerySpec = None
    response: ResponseSpec = field(default_factory=ResponseSpec)


@dataclass
class AppConfig:
    base_dir: str
    database_url: str
    init_sql: str
    tokens: dict
    endpoints: list


def _check_unknown_keys(data, allowed, where):
    for key in data:
        if key not in allowed:
            raise ConfigError("%s: unknown key %r" % (where, key))


def _validate_hook_ref(ref, where):
    if not isinstance(ref, str) or ref.count(":") != 1:
        raise ConfigError("%s: invalid hook reference %r" % (where, ref))
    module, func = ref.split(":")
    if not module or not func:
        raise ConfigError("%s: invalid hook reference %r" % (where, ref))


def _compile_fields(fields, where):
    if not isinstance(fields, dict):
        raise ConfigError("%s: response.fields must be a mapping" % where)
    compiled = {}
    for key, value in fields.items():
        if isinstance(value, dict):
            compiled[key] = _compile_fields(value, where)
        elif isinstance(value, str):
            compiled[key] = expr.parse(value)
        else:
            raise ConfigError(
                "%s: response field %r must be a string or a mapping" % (where, key)
            )
    return compiled


def _parse_params(raw_params, where):
    if not isinstance(raw_params, dict):
        raise ConfigError("%s: params must be a mapping" % where)
    params = {}
    for name, spec in raw_params.items():
        if not isinstance(spec, dict):
            raise ConfigError(
                "%s: parameter %r must be a mapping" % (where, name)
            )
        _check_unknown_keys(spec, ("in", "type", "required", "default"), where)
        if "in" not in spec:
            raise ConfigError("%s: parameter %r missing 'in'" % (where, name))
        if "type" not in spec:
            raise ConfigError("%s: parameter %r missing 'type'" % (where, name))
        location = spec["in"]
        typ = spec["type"]
        if not isinstance(location, str):
            raise ConfigError(
                "%s: parameter %r 'in' must be a string" % (where, name)
            )
        if not isinstance(typ, str):
            raise ConfigError(
                "%s: parameter %r 'type' must be a string" % (where, name)
            )
        if location not in _PARAM_LOCATIONS:
            raise ConfigError(
                "%s: unknown in location %r for parameter %r"
                % (where, location, name)
            )
        if typ not in _PARAM_TYPES:
            raise ConfigError(
                "%s: unknown type %r for parameter %r" % (where, typ, name)
            )
        if "required" in spec and not isinstance(spec["required"], bool):
            raise ConfigError(
                "%s: parameter %r 'required' must be a boolean" % (where, name)
            )
        has_default = "default" in spec
        required = spec.get("required", False)
        default = spec.get("default") if has_default else None
        params[name] = ParamSpec(
            name=name,
            location=location,
            type=typ,
            required=required,
            default=default,
            has_default=has_default,
        )
    return params


def _parse_checks(raw_checks, where):
    if not isinstance(raw_checks, list):
        raise ConfigError("%s: checks must be a list" % where)
    checks = []
    for spec in raw_checks:
        if not isinstance(spec, dict):
            raise ConfigError("%s: a check must be a mapping" % where)
        _check_unknown_keys(spec, ("when", "hook", "status", "message"), where)
        has_when = "when" in spec
        has_hook = "hook" in spec
        if has_when == has_hook:
            raise ConfigError(
                "%s: a check must have exactly one of 'when' or 'hook'" % where
            )
        status = spec.get("status", 400)
        if not isinstance(status, int) or isinstance(status, bool):
            raise ConfigError("%s: check 'status' must be an integer" % where)
        message = spec.get("message", "check failed")
        if not isinstance(message, str):
            raise ConfigError("%s: check 'message' must be a string" % where)
        if has_when:
            if not isinstance(spec["when"], str):
                raise ConfigError("%s: check 'when' must be a string" % where)
            checks.append(
                CheckSpec(
                    expression=expr.parse(spec["when"]),
                    hook=None,
                    status=status,
                    message=message,
                )
            )
        else:
            if not isinstance(spec["hook"], str):
                raise ConfigError("%s: check 'hook' must be a string" % where)
            _validate_hook_ref(spec["hook"], where)
            checks.append(
                CheckSpec(
                    expression=None,
                    hook=spec["hook"],
                    status=status,
                    message=message,
                )
            )
    return checks


def load_endpoint(data, *, source="<memory>"):
    """Load and validate one endpoint from a plain dict."""
    if not isinstance(data, dict):
        raise ConfigError("%s: endpoint must be a mapping" % source)

    _check_unknown_keys(
        data,
        ("name", "method", "path", "summary", "auth", "params",
         "checks", "query", "response"),
        source,
    )
    for key in ("name", "method", "path", "query"):
        if key not in data:
            raise ConfigError("%s: missing required %r" % (source, key))

    if not isinstance(data["name"], str):
        raise ConfigError("%s: name must be a string" % source)
    if not isinstance(data["method"], str):
        raise ConfigError("%s: method must be a string" % source)
    if not isinstance(data["path"], str):
        raise ConfigError("%s: path must be a string" % source)

    name = data["name"]
    method = data["method"].upper()
    if method not in _METHODS:
        raise ConfigError(
            "%s: unsupported method %r" % (source, data["method"])
        )
    path = data["path"]
    if not path.startswith("/"):
        raise ConfigError("%s: path must start with '/': %r" % (source, path))

    summary_raw = data.get("summary", "")
    if not isinstance(summary_raw, str):
        raise ConfigError("%s: summary must be a string" % source)

    auth = data.get("auth", "none")
    if auth not in ("required", "none"):
        raise ConfigError("%s: invalid auth mode %r" % (source, auth))

    params = _parse_params(data.get("params", {}), source)

    # A body parameter is only meaningful for a write method.
    for pname, spec in params.items():
        if spec.location == "body" and method not in ("POST", "PUT", "PATCH"):
            raise ConfigError(
                "%s: body parameter %r not allowed for %s"
                % (source, pname, method)
            )

    # Path placeholders must line up with in:path parameters, both ways.
    placeholders = re.findall(r"\{([^}]+)\}", path)
    path_params = {p for p, s in params.items() if s.location == "path"}
    for placeholder in placeholders:
        if placeholder not in path_params:
            raise ConfigError(
                "%s: path placeholder %r has no declared in:path parameter"
                % (source, placeholder)
            )
    for pname in path_params:
        if pname not in placeholders:
            raise ConfigError(
                "%s: path parameter %r is missing from the path"
                % (source, pname)
            )

    raw_query = data["query"]
    if not isinstance(raw_query, dict):
        raise ConfigError("%s: query must be a mapping" % source)
    _check_unknown_keys(raw_query, ("sql", "returns"), source)
    if "sql" not in raw_query:
        raise ConfigError("%s: query.sql is required" % source)
    if "returns" not in raw_query:
        raise ConfigError("%s: query.returns is required" % source)
    sql = raw_query["sql"]
    if not isinstance(sql, str):
        raise ConfigError("%s: query.sql must be a string" % source)
    returns = raw_query["returns"]
    if not isinstance(returns, str):
        raise ConfigError("%s: query.returns must be a string" % source)
    if returns not in _RETURNS_MODES:
        raise ConfigError(
            "%s: unknown returns mode %r" % (source, returns)
        )
    declared = set(params.keys())
    for pname in dialect.param_names(sql):
        if pname not in declared:
            raise ConfigError(
                "%s: SQL parameter %r is not a declared parameter"
                % (source, pname)
            )

    raw_response = data.get("response", {})
    if not isinstance(raw_response, dict):
        raise ConfigError("%s: response must be a mapping" % source)
    _check_unknown_keys(
        raw_response, ("status", "when_empty", "transform", "fields"), source
    )
    response_status = raw_response.get("status", 200)
    if not isinstance(response_status, int) or isinstance(response_status, bool):
        raise ConfigError("%s: response.status must be an integer" % source)
    when_empty = raw_response.get("when_empty", 404)
    if "when_empty" in raw_response and (
        not isinstance(when_empty, int) or isinstance(when_empty, bool)
    ):
        raise ConfigError(
            "%s: response.when_empty must be an integer" % source
        )
    if "when_empty" in raw_response and returns != "one":
        raise ConfigError(
            "%s: response.when_empty is only allowed when returns is 'one'"
            % source
        )
    transform = raw_response.get("transform")
    if transform is not None:
        _validate_hook_ref(transform, source)
    fields_value = raw_response.get("fields")
    fields = None
    if fields_value is not None:
        fields = _compile_fields(fields_value, source)

    checks = _parse_checks(data.get("checks", []), source)

    return Endpoint(
        name=name,
        method=method,
        path=path,
        summary=summary_raw,
        auth=auth,
        params=params,
        checks=checks,
        query=QuerySpec(sql=sql, returns=returns),
        response=ResponseSpec(
            status=response_status,
            when_empty=when_empty,
            transform=transform,
            fields=fields,
        ),
    )


def load_app(directory):
    """Load and validate the whole application from a directory."""
    if not os.path.isdir(directory):
        raise ConfigError("directory not found: %s" % directory)

    app_path = os.path.join(directory, "app.yml")
    if not os.path.isfile(app_path):
        raise ConfigError("missing app.yml in %s" % directory)
    with open(app_path, "r", encoding="utf-8") as handle:
        app_data = _safe_load(handle, "app.yml")
    if not isinstance(app_data, dict):
        raise ConfigError("app.yml: top level must be a mapping")
    _check_unknown_keys(app_data, ("database", "auth"), "app.yml")

    if "database" not in app_data:
        raise ConfigError("app.yml: missing database section")
    db = app_data["database"]
    if not isinstance(db, dict):
        raise ConfigError("app.yml: database must be a mapping")
    _check_unknown_keys(db, ("url", "init_sql"), "app.yml database")
    if "url" not in db:
        raise ConfigError("app.yml: database.url is required")
    database_url = db["url"]
    if not isinstance(database_url, str):
        raise ConfigError("app.yml: database.url must be a string")

    init_sql = None
    if "init_sql" in db:
        if not isinstance(db["init_sql"], str):
            raise ConfigError("app.yml: database.init_sql must be a string")
        init_path = os.path.join(directory, db["init_sql"])
        if not os.path.isfile(init_path):
            raise ConfigError("missing init_sql file: %s" % db["init_sql"])
        with open(init_path, "r", encoding="utf-8") as handle:
            init_sql = handle.read()

    tokens = _parse_tokens(app_data.get("auth", {}))

    endpoints_dir = os.path.join(directory, "endpoints")
    if not os.path.isdir(endpoints_dir):
        raise ConfigError("missing endpoints directory: %s" % endpoints_dir)

    names = set()
    pairs = set()
    endpoints = []
    for entry in sorted(os.listdir(endpoints_dir)):
        if not (entry.endswith(".yml") or entry.endswith(".yaml")):
            continue
        full = os.path.join(endpoints_dir, entry)
        with open(full, "r", encoding="utf-8") as handle:
            data = _safe_load(handle, entry)
        if not isinstance(data, dict):
            raise ConfigError("%s: top level must be a mapping" % entry)
        ep = load_endpoint(data, source=entry)
        if ep.name in names:
            raise ConfigError("duplicate endpoint name %r" % ep.name)
        names.add(ep.name)
        pair = (ep.method, ep.path)
        if pair in pairs:
            raise ConfigError(
                "duplicate endpoint method+path %s %s" % (ep.method, ep.path)
            )
        pairs.add(pair)
        endpoints.append(ep)

    return AppConfig(
        base_dir=directory,
        database_url=database_url,
        init_sql=init_sql,
        tokens=tokens,
        endpoints=endpoints,
    )


def _safe_load(handle, where):
    try:
        return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError("invalid YAML in %s: %s" % (where, exc))


def _parse_tokens(auth):
    if not isinstance(auth, dict):
        raise ConfigError("app.yml: auth must be a mapping")
    _check_unknown_keys(auth, ("tokens",), "app.yml auth")
    raw = auth.get("tokens", [])
    if not isinstance(raw, list):
        raise ConfigError("app.yml: auth.tokens must be a list")
    tokens = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ConfigError("app.yml: a token must be a mapping")
        _check_unknown_keys(
            entry, ("token", "token_env", "subject", "roles"),
            "app.yml token",
        )
        has_token = "token" in entry
        has_token_env = "token_env" in entry
        if has_token == has_token_env:
            raise ConfigError(
                "app.yml: a token must have exactly one of "
                "'token' or 'token_env'"
            )
        if "subject" not in entry:
            raise ConfigError("app.yml: a token needs a subject")
        subject = entry["subject"]
        if not isinstance(subject, str):
            raise ConfigError("app.yml: a token subject must be a string")
        roles = entry.get("roles", [])
        # `roles: "admin"` would make `'admin' in auth.roles` a substring
        # match, so a role named "adm" would pass an admin-only check.
        if not isinstance(roles, list) or not all(
            isinstance(role, str) for role in roles
        ):
            raise ConfigError("app.yml: token roles must be a list of strings")
        if has_token:
            # Never str() this: `token: null` would become the usable token
            # string "None".
            value = entry["token"]
            if not isinstance(value, str):
                raise ConfigError("app.yml: a token must be a string")
        else:
            variable = entry["token_env"]
            if not isinstance(variable, str):
                raise ConfigError("app.yml: token_env must be a string")
            value = os.environ.get(variable)
            if value is None:
                raise ConfigError(
                    "app.yml: environment variable %s is not set" % variable
                )
        tokens[value] = {"subject": subject, "roles": roles}
    return tokens
