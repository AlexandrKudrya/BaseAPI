"""Resolving ``"module:function"`` references to real callables.

``resolve_hook`` imports the user's ``hooks.py`` or an arbitrary module from
their API directory and returns the named callable. The function is resolved
but never called here.
"""

import importlib
import os
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
        # A bare module name is cached in sys.modules by name import. If an
        # earlier resolve imported it from another directory, re-import it from
        # this one so two API projects with the same hooks.py stay separate.
        _drop_modules_not_in(module_path, base_dir)
        sys.path.insert(0, base_dir)
        try:
            return _resolve(module_path, attr)
        finally:
            try:
                sys.path.remove(base_dir)
            except ValueError:
                pass
    return _resolve(module_path, attr)


def _drop_modules_not_in(module_path, base_dir):
    """Drop cached modules for ``module_path`` that were not imported here."""
    top_level = module_path.split(".")[0]
    prefix = top_level + "."
    base = os.path.realpath(base_dir)
    for name in list(sys.modules):
        if name != top_level and not name.startswith(prefix):
            continue
        mod = sys.modules.get(name)
        if mod is None:
            continue
        file_path = getattr(mod, "__file__", None)
        if file_path is None:
            continue
        if not _is_inside(base, os.path.realpath(file_path)):
            del sys.modules[name]


def _is_inside(base, path):
    try:
        return os.path.commonpath([base, path]) == base
    except ValueError:
        return False


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
