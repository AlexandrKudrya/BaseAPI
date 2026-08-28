"""Hooks for the example notes API.

A hook is a plain Python function referenced from YAML as
``"module:function"``. The module lives next to ``app.yml`` (in this
directory). Two kinds of hook exist:

- a *check* hook, ``def hook(ctx)``, must return a truthy value to let the
  request through;
- a *transform* hook, ``def hook(body, ctx)``, rewrites the response body.
"""


def is_admin(ctx):
    """Check hook: allow only callers whose identity carries the admin role."""
    return "admin" in ctx["auth"]["roles"]
