"""The FastAPI layer, driven over HTTP against a throwaway API project."""

import os
import sys
import tempfile
import textwrap
import unittest

from fastapi.testclient import TestClient

from baseapi.app import create_app
from baseapi.errors import ConfigError

HOOKS_MODULE = "baseapi_test_app_hooks"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    owner TEXT NOT NULL
);
INSERT INTO notes (id, title, body, owner)
    SELECT 1, 'first', 'hello', 'alice'
    WHERE NOT EXISTS (SELECT 1 FROM notes WHERE id = 1);
INSERT INTO notes (id, title, body, owner)
    SELECT 2, 'second', 'world', 'bob'
    WHERE NOT EXISTS (SELECT 1 FROM notes WHERE id = 2);
"""

HOOKS = """
def is_owner(ctx):
    return ctx["auth"]["subject"] == "alice"


def add_count(body, ctx):
    return {"items": body, "count": len(body)}
"""


class ApiProject:
    """Builds a small API project on disk."""

    def __init__(self, directory):
        self.dir = directory
        os.makedirs(os.path.join(self.dir, "endpoints"), exist_ok=True)

    def write(self, relative_path, text):
        full = os.path.join(self.dir, relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = ApiProject(self._tmp.name)
        self.addCleanup(sys.modules.pop, HOOKS_MODULE, None)
        self.build()

    def build(self):
        self.project.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
              init_sql: "schema.sql"
            auth:
              tokens:
                - token: "alice-token"
                  subject: "alice"
                  roles: ["admin"]
                - token: "bob-token"
                  subject: "bob"
                  roles: []
        """)
        self.project.write("schema.sql", SCHEMA)
        self.project.write(HOOKS_MODULE + ".py", HOOKS)

        self.project.write("endpoints/list_notes.yml", """
            name: list_notes
            method: GET
            path: /notes
            query:
              sql: "SELECT id, title, body FROM notes ORDER BY id"
              returns: many
            response:
              fields:
                id: "row.id"
                title: "row.title"
                text: "row.body"
        """)

        self.project.write("endpoints/get_note.yml", """
            name: get_note
            method: GET
            path: /notes/{note_id}
            params:
              note_id: { in: path, type: int, required: true }
            checks:
              - when: "params.note_id > 0"
                status: 400
                message: "note_id must be positive"
            query:
              sql: "SELECT id, title, body FROM notes WHERE id = :note_id"
              returns: one
            response:
              when_empty: 404
              fields:
                id: "row.id"
                title: "row.title"
        """)

        self.project.write("endpoints/create_note.yml", """
            name: create_note
            method: POST
            path: /notes
            auth: required
            params:
              title:   { in: body, type: str, required: true }
              body:    { in: body, type: str, required: true }
              subject: { in: auth, type: str, required: true }
            query:
              sql: >
                INSERT INTO notes (title, body, owner)
                VALUES (:title, :body, :subject)
                RETURNING id
              returns: one
            response:
              status: 201
              fields:
                id: "row.id"
                owner: "auth.subject"
        """)

        self.project.write("endpoints/delete_note.yml", """
            name: delete_note
            method: DELETE
            path: /notes/{note_id}
            auth: required
            params:
              note_id: { in: path, type: int, required: true }
            checks:
              - hook: "%s:is_owner"
                status: 403
                message: "only alice may delete"
            query:
              sql: "DELETE FROM notes WHERE id = :note_id"
              returns: none
            response:
              fields:
                deleted: "result.rowcount"
        """ % HOOKS_MODULE)

    def client(self):
        client = TestClient(create_app(self.project.dir),
                            raise_server_exceptions=False)
        self.addCleanup(client.close)
        return client


class TestReading(AppTestCase):
    def test_a_list_endpoint(self):
        response = self.client().get("/notes")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [
            {"id": 1, "title": "first", "text": "hello"},
            {"id": 2, "title": "second", "text": "world"},
        ])

    def test_a_path_parameter_reaches_the_query(self):
        response = self.client().get("/notes/2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": 2, "title": "second"})

    def test_the_response_is_json(self):
        response = self.client().get("/notes/1")
        self.assertIn("application/json", response.headers["content-type"])

    def test_a_missing_row_uses_when_empty(self):
        response = self.client().get("/notes/999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], 404)

    def test_an_uncoercible_path_parameter_is_422(self):
        response = self.client().get("/notes/abc")
        self.assertEqual(response.status_code, 422)
        self.assertIn("note_id", response.json()["error"]["message"])

    def test_a_failing_check_uses_the_authors_status_and_message(self):
        response = self.client().get("/notes/0")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["message"],
                         "note_id must be positive")

    def test_an_undeclared_route_is_404(self):
        self.assertEqual(self.client().get("/nope").status_code, 404)

    def test_an_undeclared_method_on_a_declared_path_is_405(self):
        self.assertEqual(self.client().put("/notes").status_code, 405)


class TestAuth(AppTestCase):
    def test_a_protected_endpoint_without_a_token_is_401(self):
        response = self.client().post("/notes",
                                      json={"title": "t", "body": "b"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], 401)

    def test_an_unknown_token_is_401(self):
        response = self.client().post(
            "/notes", json={"title": "t", "body": "b"},
            headers={"Authorization": "Bearer nope"},
        )
        self.assertEqual(response.status_code, 401)

    def test_a_valid_token_is_accepted(self):
        response = self.client().post(
            "/notes", json={"title": "t", "body": "b"},
            headers={"Authorization": "Bearer alice-token"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["owner"], "alice")

    def test_an_open_endpoint_does_not_need_a_token(self):
        self.assertEqual(self.client().get("/notes").status_code, 200)

    def test_an_open_endpoint_ignores_a_bad_token(self):
        response = self.client().get(
            "/notes", headers={"Authorization": "Bearer garbage"})
        self.assertEqual(response.status_code, 200)


class TestWriting(AppTestCase):
    def test_a_created_row_is_visible_to_a_later_read(self):
        client = self.client()
        created = client.post(
            "/notes", json={"title": "third", "body": "!"},
            headers={"Authorization": "Bearer alice-token"},
        )
        self.assertEqual(created.status_code, 201)
        new_id = created.json()["id"]
        fetched = client.get(f"/notes/{new_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["title"], "third")

    def test_a_missing_body_field_is_422(self):
        response = self.client().post(
            "/notes", json={"title": "only"},
            headers={"Authorization": "Bearer alice-token"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("body", response.json()["error"]["message"])

    def test_a_missing_request_body_entirely_is_422(self):
        response = self.client().post(
            "/notes", headers={"Authorization": "Bearer alice-token"})
        self.assertEqual(response.status_code, 422)

    def test_a_delete_reports_the_row_count(self):
        response = self.client().delete(
            "/notes/1", headers={"Authorization": "Bearer alice-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": 1})

    def test_a_delete_that_matched_nothing_reports_zero(self):
        response = self.client().delete(
            "/notes/999", headers={"Authorization": "Bearer alice-token"})
        self.assertEqual(response.json(), {"deleted": 0})

    def test_a_hook_check_denies_the_wrong_subject(self):
        response = self.client().delete(
            "/notes/1", headers={"Authorization": "Bearer bob-token"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["message"],
                         "only alice may delete")

    def test_a_denied_delete_does_not_remove_the_row(self):
        client = self.client()
        client.delete("/notes/1",
                      headers={"Authorization": "Bearer bob-token"})
        self.assertEqual(client.get("/notes/1").status_code, 200)


class TestTransformHook(AppTestCase):
    def build(self):
        super().build()
        self.project.write("endpoints/list_notes.yml", """
            name: list_notes
            method: GET
            path: /notes
            query:
              sql: "SELECT id FROM notes ORDER BY id"
              returns: many
            response:
              transform: "%s:add_count"
              fields:
                id: "row.id"
        """ % HOOKS_MODULE)

    def test_the_transform_rewrites_the_body(self):
        response = self.client().get("/notes")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(),
                         {"items": [{"id": 1}, {"id": 2}], "count": 2})


class TestStartupFailures(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = ApiProject(self._tmp.name)

    def test_an_invalid_endpoint_fails_at_create_app_not_at_request_time(self):
        self.project.write("app.yml",
                           'database:\n  url: "sqlite:///:memory:"\n')
        self.project.write("endpoints/bad.yml", """
            name: bad
            method: GET
            path: /bad
            query:
              sql: "SELECT id FROM notes WHERE id = :undeclared"
              returns: one
        """)
        with self.assertRaises(ConfigError):
            create_app(self.project.dir)

    def test_an_unresolvable_hook_fails_at_create_app(self):
        self.project.write("app.yml",
                           'database:\n  url: "sqlite:///:memory:"\n')
        self.project.write("endpoints/bad.yml", """
            name: bad
            method: GET
            path: /bad
            checks:
              - hook: "no_such_hooks_module:nope"
                status: 403
                message: "no"
            query:
              sql: "SELECT 1 AS n"
              returns: one
        """)
        with self.assertRaises(ConfigError):
            create_app(self.project.dir)

    def test_a_missing_directory_fails_at_create_app(self):
        with self.assertRaises(ConfigError):
            create_app(os.path.join(self.project.dir, "nope"))


if __name__ == "__main__":
    unittest.main()
