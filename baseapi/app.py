"""The FastAPI layer.

This module does HTTP and nothing else: it loads configuration, wires hooks
and a database into closures, registers one route per endpoint, collects the
raw request into the values ``pipeline.handle`` expects and serialises its
``(status, body)`` result as a JSON response. No validation, business logic or
mapping lives here.
"""

import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from baseapi import auth, db, hooks, pipeline
from baseapi.config import load_app
from baseapi.errors import ApiError

_BODY_METHODS = ("POST", "PUT", "PATCH")


def create_app(directory):
    """Build a FastAPI application from a YAML API directory."""
    config = load_app(directory)

    resolved_hooks = {}
    for endpoint in config.endpoints:
        for check in endpoint.checks:
            if check.hook is not None:
                resolved_hooks[check.hook] = hooks.resolve_hook(
                    check.hook, base_dir=config.base_dir
                )
        if endpoint.response.transform is not None:
            resolved_hooks[endpoint.response.transform] = hooks.resolve_hook(
                endpoint.response.transform, base_dir=config.base_dir
            )

    database = db.connect(
        config.database_url,
        base_dir=config.base_dir,
        init_sql=config.init_sql,
    )

    app = FastAPI()
    # Starlette matches routes in registration order, and endpoints arrive in
    # sorted-filename order, so without this a `/things/{id}` route declared in
    # an earlier-sorting file would swallow `/things/count`. Register the more
    # specific path first instead, and the filename stops mattering.
    for endpoint in sorted(config.endpoints, key=_specificity):
        app.add_api_route(
            endpoint.path,
            _make_handler(endpoint, database, resolved_hooks, config.tokens),
            methods=[endpoint.method],
        )
    return app


def _specificity(endpoint):
    """Sort key placing literal segments ahead of placeholders."""
    return [
        (1, "") if segment.startswith("{") else (0, segment)
        for segment in endpoint.path.split("/")
    ]


def _make_handler(endpoint, database, resolved_hooks, tokens):
    async def handler(request: Request):
        path = dict(request.path_params)
        query = dict(request.query_params)
        headers = dict(request.headers)

        body = None
        if endpoint.method in _BODY_METHODS:
            raw = await request.body()
            if raw:
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = None

        identity = auth.ANONYMOUS
        if endpoint.auth == "required":
            try:
                identity = auth.authenticate(
                    headers.get("authorization"), tokens
                )
            except ApiError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content={"error": {"code": exc.status,
                                       "message": exc.message}},
                )

        status, value = pipeline.handle(
            endpoint,
            db=database,
            path=path,
            query=query,
            body=body,
            headers=headers,
            auth=identity,
            hooks=resolved_hooks,
        )
        return JSONResponse(status_code=status, content=value)

    return handler
