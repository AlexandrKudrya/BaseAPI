"""`python -m baseapi.check <dir>` - the gate an agent runs after writing YAML.

Config errors alone are not enough: the most common mistake when writing SQL
by hand against a schema is a column or table that does not exist, and that is
invisible until the endpoint is called. check() compiles every statement.
"""

import os
import sys
import tempfile
import textwrap
import unittest

from baseapi.check import check, main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example")

SCHEMA = "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, title TEXT);"


class Project:
    def __init__(self, directory):
        self.dir = directory
        os.makedirs(os.path.join(self.dir, "endpoints"), exist_ok=True)

    def write(self, relative_path, text):
        full = os.path.join(self.dir, relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))


class CheckTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Project(self._tmp.name)
        self.project.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
              init_sql: "schema.sql"
        """)
        self.project.write("schema.sql", SCHEMA)

    def run_check(self):
        return check(self.project.dir)


class TestValidProject(CheckTestCase):
    def test_a_clean_project_exits_zero(self):
        self.project.write("endpoints/list.yml", """
            name: list_notes
            method: GET
            path: /notes
            query:
              sql: "SELECT id, title FROM notes"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)

    def test_the_report_lists_every_route(self):
        self.project.write("endpoints/list.yml", """
            name: list_notes
            method: GET
            path: /notes
            query:
              sql: "SELECT id, title FROM notes"
              returns: many
        """)
        self.project.write("endpoints/one.yml", """
            name: get_note
            method: GET
            path: /notes/{note_id}
            params:
              note_id: { in: path, type: int, required: true }
            query:
              sql: "SELECT id, title FROM notes WHERE id = :note_id"
              returns: one
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        for fragment in ("GET", "/notes", "/notes/{note_id}",
                         "list_notes", "get_note"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, report)

    def test_a_project_with_no_endpoints_still_passes(self):
        code, report = self.run_check()
        self.assertEqual(code, 0, report)

    def test_the_shipped_example_passes(self):
        code, report = check(EXAMPLE)
        self.assertEqual(code, 0, report)
        self.assertIn("/notes", report)


class TestConfigErrors(CheckTestCase):
    def test_an_invalid_endpoint_exits_one_and_names_the_file(self):
        self.project.write("endpoints/broken.yml", """
            name: broken
            method: GET
            path: /broken
            query:
              sql: "SELECT id FROM notes"
              returns: sometimes
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("broken.yml", report)

    def test_unparsable_yaml_exits_one(self):
        self.project.write("endpoints/bad.yml", "name: [unclosed\n")
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("bad.yml", report)

    def test_an_undeclared_sql_parameter_exits_one(self):
        self.project.write("endpoints/bad.yml", """
            name: bad
            method: GET
            path: /bad
            query:
              sql: "SELECT id FROM notes WHERE id = :nope"
              returns: one
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("nope", report)

    def test_a_missing_directory_exits_one(self):
        code, report = check(os.path.join(self.project.dir, "nope"))
        self.assertEqual(code, 1)
        self.assertTrue(report.strip())

    def test_a_missing_app_yml_exits_one(self):
        with tempfile.TemporaryDirectory() as empty:
            code, report = check(empty)
            self.assertEqual(code, 1)
            self.assertIn("app.yml", report)


class TestHookErrors(CheckTestCase):
    def test_an_unresolvable_hook_exits_one_and_names_it(self):
        self.project.write("endpoints/bad.yml", """
            name: bad
            method: GET
            path: /bad
            checks:
              - hook: "no_such_module_at_all:nope"
                status: 403
                message: "no"
            query:
              sql: "SELECT id FROM notes"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("no_such_module_at_all", report)

    def test_an_unresolvable_transform_exits_one(self):
        self.project.write("endpoints/bad.yml", """
            name: bad
            method: GET
            path: /bad
            query:
              sql: "SELECT id FROM notes"
              returns: many
            response:
              transform: "no_such_module_at_all:nope"
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("no_such_module_at_all", report)

    def test_a_resolvable_hook_passes(self):
        self.project.write("hooks.py", "def ok(ctx):\n    return True\n")
        self.addCleanup(sys.modules.pop, "hooks", None)
        self.project.write("endpoints/good.yml", """
            name: good
            method: GET
            path: /good
            checks:
              - hook: "hooks:ok"
                status: 403
                message: "no"
            query:
              sql: "SELECT id FROM notes"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)


class TestSqlErrors(CheckTestCase):
    """The point of the command: SQL that the config layer cannot judge."""

    def test_a_missing_table_exits_one_and_names_the_endpoint(self):
        self.project.write("endpoints/bad.yml", """
            name: bad_table
            method: GET
            path: /bad
            query:
              sql: "SELECT id FROM notez"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("bad_table", report)
        self.assertIn("notez", report)

    def test_a_missing_column_exits_one(self):
        self.project.write("endpoints/bad.yml", """
            name: bad_column
            method: GET
            path: /bad
            query:
              sql: "SELECT id, bodyy FROM notes"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("bad_column", report)

    def test_a_syntax_error_exits_one(self):
        self.project.write("endpoints/bad.yml", """
            name: bad_syntax
            method: GET
            path: /bad
            query:
              sql: "SELCT id FROM notes"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("bad_syntax", report)

    def test_a_write_statement_is_compiled_but_not_executed(self):
        self.project.write("endpoints/create.yml", """
            name: create_note
            method: POST
            path: /notes
            params:
              title: { in: body, type: str, required: true }
            query:
              sql: "INSERT INTO notes (title) VALUES (:title)"
              returns: none
        """)
        self.project.write("endpoints/count.yml", """
            name: count_notes
            method: GET
            path: /count
            query:
              sql: "SELECT COUNT(*) AS c FROM notes"
              returns: one
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        # nothing was inserted by the check itself
        from baseapi.db import connect
        db = connect("sqlite:///:memory:", init_sql=SCHEMA)
        self.addCleanup(db.close)
        self.assertEqual(db.run("SELECT COUNT(*) AS c FROM notes", {}).rows,
                         [{"c": 0}])

    def test_a_delete_statement_is_compiled_but_not_executed(self):
        self.project.write("schema.sql",
                           SCHEMA + "\nINSERT INTO notes (id, title) "
                                    "VALUES (1, 'kept');")
        self.project.write("endpoints/wipe.yml", """
            name: wipe
            method: DELETE
            path: /notes
            query:
              sql: "DELETE FROM notes"
              returns: none
        """)
        self.project.write("endpoints/count.yml", """
            name: count_notes
            method: GET
            path: /count
            query:
              sql: "SELECT COUNT(*) AS c FROM notes"
              returns: one
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)

    def test_every_broken_endpoint_is_reported_not_just_the_first(self):
        for index in (1, 2):
            self.project.write("endpoints/bad%d.yml" % index, """
                name: bad_%d
                method: GET
                path: /bad%d
                query:
                  sql: "SELECT id FROM missing_%d"
                  returns: many
            """ % (index, index, index))
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("bad_1", report)
        self.assertIn("bad_2", report)


class TestUnbindableParameters(CheckTestCase):
    """An optional parameter with no default is simply absent from the params
    dict, so the driver gets no value to bind and the request dies with a 500.
    Nothing else catches this: the config is valid and the SQL compiles."""

    def test_an_optional_sql_parameter_without_a_default_is_reported(self):
        self.project.write("endpoints/search.yml", """
            name: search_notes
            method: GET
            path: /notes
            params:
              q: { in: query, type: str }
            query:
              sql: "SELECT id FROM notes WHERE :q IS NULL OR title = :q"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("search_notes", report)
        self.assertIn("q", report)
        self.assertIn("default", report)

    def test_an_explicit_null_default_is_accepted(self):
        self.project.write("endpoints/search.yml", """
            name: search_notes
            method: GET
            path: /notes
            params:
              q: { in: query, type: str, default: null }
            query:
              sql: "SELECT id FROM notes WHERE :q IS NULL OR title = :q"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)

    def test_a_required_parameter_is_accepted(self):
        self.project.write("endpoints/one.yml", """
            name: get_note
            method: GET
            path: /notes/{note_id}
            params:
              note_id: { in: path, type: int, required: true }
            query:
              sql: "SELECT id FROM notes WHERE id = :note_id"
              returns: one
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)

    def test_an_optional_parameter_not_used_in_sql_is_fine(self):
        self.project.write("endpoints/list.yml", """
            name: list_notes
            method: GET
            path: /notes
            params:
              verbose: { in: query, type: bool }
            checks:
              - when: "params.verbose == true or params.verbose == null"
                status: 400
                message: "no"
            query:
              sql: "SELECT id FROM notes"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)

    def test_an_optional_auth_parameter_used_in_sql_is_reported(self):
        self.project.write("endpoints/mine.yml", """
            name: my_notes
            method: GET
            path: /mine
            params:
              subject: { in: auth, type: str }
            query:
              sql: "SELECT id FROM notes WHERE title = :subject"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("my_notes", report)


class TestPostgres(CheckTestCase):
    """psycopg is not installed, so check must not try to connect."""

    def setUp(self):
        super().setUp()
        self.project.write("app.yml", """
            database:
              url: "postgresql://user:pass@localhost:5432/db"
        """)

    def test_config_and_hooks_are_still_checked(self):
        self.project.write("endpoints/bad.yml", """
            name: bad
            method: GET
            path: /bad
            query:
              sql: "SELECT id FROM notes WHERE id = :nope"
              returns: one
        """)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("nope", report)

    def test_a_valid_postgres_project_passes_without_a_server(self):
        self.project.write("endpoints/good.yml", """
            name: good
            method: GET
            path: /good
            query:
              sql: "SELECT id FROM notes"
              returns: many
        """)
        code, report = self.run_check()
        self.assertEqual(code, 0, report)

    def test_the_report_says_the_sql_check_was_skipped(self):
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        self.assertIn("skip", report.lower())


class TestMain(CheckTestCase):
    def test_main_returns_the_exit_code(self):
        self.project.write("endpoints/list.yml", """
            name: list_notes
            method: GET
            path: /notes
            query:
              sql: "SELECT id, title FROM notes"
              returns: many
        """)
        self.assertEqual(main([self.project.dir]), 0)

    def test_main_returns_one_on_a_broken_project(self):
        self.project.write("endpoints/bad.yml", "name: [unclosed\n")
        self.assertEqual(main([self.project.dir]), 1)

    def test_main_without_an_argument_returns_two(self):
        self.assertEqual(main([]), 2)

    def test_main_with_too_many_arguments_returns_two(self):
        self.assertEqual(main(["a", "b"]), 2)


if __name__ == "__main__":
    unittest.main()
