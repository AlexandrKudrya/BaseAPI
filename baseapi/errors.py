"""Framework exceptions.

Two exception types are used across the whole framework:

- ``ConfigError`` — anything wrong in the YAML or in wiring. Always raised
  while loading configuration, never during a request.
- ``ApiError`` — a request failure carrying an HTTP ``status`` and a
  ``message`` that becomes the response body.
"""


class ConfigError(Exception):
    """Raised for anything wrong in the YAML or in wiring, at load time."""


class ApiError(Exception):
    """A request failure carrying an HTTP status and a message."""

    def __init__(self, status, message):
        self.status = int(status)
        self.message = str(message)
        super().__init__(self.message)
