"""Uvicorn entry point: build the app from the example directory."""

import os

from baseapi.app import create_app

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DIR = os.path.join(_BASE_DIR, "example")

app = create_app(os.environ.get("BASEAPI_DIR", _DEFAULT_DIR))
