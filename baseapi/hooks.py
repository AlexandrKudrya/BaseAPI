"""Resolving ``"module:function"`` references to real callables.

``resolve_hook`` imports the user's ``hooks.py`` or an arbitrary module from
their API directory and returns the named callable. The function is resolved
but never called here.
"""

import importlib
import sys

from baseapi.errors import ConfigError


def resolve_hook(ref, *, base_dir=None):
    """Return the callable named by ``ref``, a ``module:function`` string."""
    if not isinstance(ref, str) or ref.count(":") != 1:
        raise ConfigError("invalid hook reference: %r" % ref)
    module_path, attr = ref.split(":")
    if not module_path or not attr:
        raise ConfigError("invalid hook reference: %r" % ref)

    if base_dir is not None:
        sys.path.insert(0, base_dir)
        try:
            return _resolve(module_path, attr)
        finally:
            try:
                sys.path.remove(base_dir)
            except ValueError:
                pass
    return _resolve(module_path, attr)


def _resolve(module_path, attr):
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001 - any import failure is a ConfigError
        raise ConfigError(
            "cannot import hook module %r: %s" % (module_path, exc)
        )
    try:
        value = getattr(module, attr)
    except AttributeError:
        raise ConfigError(
            "hook module %r has no attribute %r" % (module_path, attr)
        )
    if not callable(value):
        raise ConfigError("hook attribute %r is not callable" % attr)
    return value
