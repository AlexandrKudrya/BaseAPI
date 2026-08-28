"""Resolving "module:function" references to real callables."""

import os
import sys
import tempfile
import unittest

from baseapi.errors import ConfigError
from baseapi.hooks import resolve_hook


class TestResolveHook(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self._path_before = list(sys.path)
        self.addCleanup(self._restore_path)

    def _restore_path(self):
        sys.path[:] = self._path_before

    def write_module(self, name, body):
        with open(os.path.join(self.dir, name + ".py"), "w",
                  encoding="utf-8") as handle:
            handle.write(body)
        self.addCleanup(sys.modules.pop, name, None)

    def test_resolves_a_module_next_to_the_api_directory(self):
        self.write_module("hooks_ok", "def can_read(ctx):\n    return True\n")
        fn = resolve_hook("hooks_ok:can_read", base_dir=self.dir)
        self.assertTrue(callable(fn))
        self.assertIs(fn({}), True)

    def test_the_hook_receives_the_context_it_is_given(self):
        self.write_module(
            "hooks_ctx",
            "def is_admin(ctx):\n"
            "    return 'admin' in ctx['auth']['roles']\n",
        )
        fn = resolve_hook("hooks_ctx:is_admin", base_dir=self.dir)
        self.assertIs(fn({"auth": {"roles": ["admin"]}}), True)
        self.assertIs(fn({"auth": {"roles": []}}), False)

    def test_resolves_a_dotted_module_path(self):
        package = os.path.join(self.dir, "pkg_hooks")
        os.makedirs(package)
        open(os.path.join(package, "__init__.py"), "w").close()
        with open(os.path.join(package, "checks.py"), "w",
                  encoding="utf-8") as handle:
            handle.write("def always(ctx):\n    return True\n")
        self.addCleanup(sys.modules.pop, "pkg_hooks", None)
        self.addCleanup(sys.modules.pop, "pkg_hooks.checks", None)
        fn = resolve_hook("pkg_hooks.checks:always", base_dir=self.dir)
        self.assertIs(fn({}), True)

    def test_works_without_a_base_dir_for_an_importable_module(self):
        fn = resolve_hook("json:dumps")
        self.assertEqual(fn([1]), "[1]")

    def test_the_base_dir_is_not_left_on_sys_path(self):
        self.write_module("hooks_clean", "def f(ctx):\n    return True\n")
        resolve_hook("hooks_clean:f", base_dir=self.dir)
        self.assertNotIn(self.dir, sys.path)

    def test_rejects_a_reference_without_a_colon(self):
        with self.assertRaises(ConfigError):
            resolve_hook("hooks.can_read", base_dir=self.dir)

    def test_rejects_an_empty_half(self):
        for ref in ("hooks:", ":can_read", ":", ""):
            with self.subTest(ref=ref):
                with self.assertRaises(ConfigError):
                    resolve_hook(ref, base_dir=self.dir)

    def test_rejects_more_than_one_colon(self):
        with self.assertRaises(ConfigError):
            resolve_hook("hooks:a:b", base_dir=self.dir)

    def test_a_missing_module_is_a_config_error_naming_it(self):
        with self.assertRaises(ConfigError) as caught:
            resolve_hook("no_such_module_here:f", base_dir=self.dir)
        self.assertIn("no_such_module_here", str(caught.exception))

    def test_a_missing_function_is_a_config_error_naming_it(self):
        self.write_module("hooks_partial", "def other(ctx):\n    return True\n")
        with self.assertRaises(ConfigError) as caught:
            resolve_hook("hooks_partial:missing", base_dir=self.dir)
        self.assertIn("missing", str(caught.exception))

    def test_a_non_callable_attribute_is_a_config_error(self):
        self.write_module("hooks_value", "LIMIT = 5\n")
        with self.assertRaises(ConfigError):
            resolve_hook("hooks_value:LIMIT", base_dir=self.dir)

    def test_a_module_that_fails_to_import_is_a_config_error(self):
        self.write_module("hooks_boom", "raise ValueError('boom')\n")
        with self.assertRaises(ConfigError):
            resolve_hook("hooks_boom:f", base_dir=self.dir)


if __name__ == "__main__":
    unittest.main()
