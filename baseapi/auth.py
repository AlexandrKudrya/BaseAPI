"""Static bearer-token authentication.

Tokens are the literal strings declared in ``app.yml``. There is no hashing,
no signing, no expiry and no database lookup.
"""

from baseapi.errors import ApiError

ANONYMOUS = {"subject": None, "roles": []}


def authenticate(header_value, tokens):
    """Turn an ``Authorization`` header into an identity, or raise 401."""
    if header_value is None or not header_value.strip():
        raise ApiError(401, "missing authorization header")

    parts = header_value.strip().split(None, 1)
    if len(parts) != 2:
        raise ApiError(401, "malformed authorization header")
    scheme, token = parts
    if scheme.lower() != "bearer":
        raise ApiError(401, "unsupported authorization scheme")
    token = token.strip()
    if not token:
        raise ApiError(401, "missing bearer token")

    identity = tokens.get(token)
    if identity is None:
        raise ApiError(401, "unknown token")

    # Return a fresh copy so callers cannot mutate the configuration.
    return {
        "subject": identity["subject"],
        "roles": list(identity["roles"]),
    }
