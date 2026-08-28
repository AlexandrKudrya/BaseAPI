"""Turning query rows into the response body.

A pure module: no I/O, no clock. ``build_body`` evaluates a ``fields``
structure (callables plus nested mappings of the same shape) against a
``context`` dict. It never mutates the context or the rows it reads.
"""


def build_body(fields, context, returns):
    if returns == "one":
        if fields is None:
            return dict(context["row"])
        return _evaluate(fields, context)

    if returns == "many":
        if fields is None:
            return list(context.get("rows") or [])
        body = []
        for row in context.get("rows") or []:
            item_context = dict(context)
            item_context["row"] = row
            body.append(_evaluate(fields, item_context))
        return body

    if returns == "none":
        if fields is None:
            return {"rowcount": context["result"]["rowcount"]}
        return _evaluate(fields, context)

    raise ValueError("unknown returns mode: %r" % returns)


def _evaluate(fields, context):
    body = {}
    for key, value in fields.items():
        if isinstance(value, dict):
            body[key] = _evaluate(value, context)
        else:
            body[key] = value(context)
    return body
