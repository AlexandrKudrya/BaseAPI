"""The shipped example project must load and answer for real."""

import os
import unittest

from fastapi.testclient import TestClient

from baseapi.app import create_app
from baseapi.config import load_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example")

DEV = {"Authorization": "Bearer dev-token"}
READER = {"Authorization": "Bearer reader-token"}


class TestExampleFiles(unittest.TestCase):
    def test_the_example_directory_exists(self):
        self.assertTrue(os.path.isdir(EXAMPLE), EXAMPLE)

    def test_it_has_the_expected_files(self):
        for relative in ("app.yml", "schema.sql", "hooks.py",
                         "endpoints/list_notes.yml", "endpoints/get_note.yml",
                         "endpoints/create_note.yml",
                         "endpoints/delete_note.yml"):
            with self.subTest(path=relative):
                self.assertTrue(
                    os.path.isfile(os.path.join(EXAMPLE, relative)), relative)

    def test_the_format_reference_exists_and_is_not_a_stub(self):
        path = os.path.join(ROOT, "FORMAT.md")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertGreater(len(text), 1500)
        for keyword in ("app.yml", "params", "checks", "query", "response",
                        "returns", "when_empty", "hook", "auth"):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, text)


class TestExampleConfig(unittest.TestCase):
    def test_it_loads(self):
        app = load_app(EXAMPLE)
        self.assertEqual(
            sorted(e.name for e in app.endpoints),
            ["create_note", "delete_note", "get_note", "list_notes"],
        )

    def test_the_routes_are_the_documented_ones(self):
        app = load_app(EXAMPLE)
        routes = sorted((e.method, e.path) for e in app.endpoints)
        self.assertEqual(routes, [
            ("DELETE", "/notes/{note_id}"),
            ("GET", "/notes"),
            ("GET", "/notes/{note_id}"),
            ("POST", "/notes"),
        ])

    def test_both_documented_tokens_are_configured(self):
        app = load_app(EXAMPLE)
        self.assertEqual(app.tokens["dev-token"]["subject"], "alice")
        self.assertEqual(app.tokens["reader-token"]["subject"], "bob")

    def test_it_runs_in_memory_and_leaves_no_database_file_behind(self):
        app = load_app(EXAMPLE)
        self.assertIn(":memory:", app.database_url)
        client = TestClient(create_app(EXAMPLE))
        self.addCleanup(client.close)
        client.get("/notes")
        strays = [name for name in os.listdir(EXAMPLE)
                  if name.endswith(".db")]
        self.assertEqual(strays, [])


class TestExampleOverHttp(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(EXAMPLE),
                                 raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def test_the_list_endpoint_returns_the_seeded_notes(self):
        response = self.client.get("/notes")
        self.assertEqual(response.status_code, 200)
        notes = response.json()
        self.assertIsInstance(notes, list)
        self.assertEqual(len(notes), 2)
        self.assertEqual([n["id"] for n in notes], [1, 2])
        for note in notes:
            self.assertEqual(set(note), {"id", "title", "text", "owner"})
            self.assertIsInstance(note["title"], str)
            self.assertTrue(note["title"])

    def test_fetching_one_note(self):
        response = self.client.get("/notes/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 1)

    def test_fetching_a_missing_note_is_404(self):
        response = self.client.get("/notes/9999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], 404)

    def test_a_non_positive_id_is_rejected_by_the_check(self):
        response = self.client.get("/notes/0")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["error"]["message"])

    def test_a_non_numeric_id_is_422(self):
        response = self.client.get("/notes/abc")
        self.assertEqual(response.status_code, 422)

    def test_creating_a_note_needs_a_token(self):
        response = self.client.post("/notes",
                                    json={"title": "t", "body": "b"})
        self.assertEqual(response.status_code, 401)

    def test_creating_a_note_with_a_token_returns_201_and_the_new_id(self):
        response = self.client.post(
            "/notes", json={"title": "from test", "body": "b"}, headers=DEV)
        self.assertEqual(response.status_code, 201)
        new_id = response.json()["id"]
        self.assertIsInstance(new_id, int)
        self.assertGreater(new_id, 2)

    def test_a_created_note_is_owned_by_the_caller(self):
        created = self.client.post(
            "/notes", json={"title": "owned", "body": "b"}, headers=DEV)
        new_id = created.json()["id"]
        listed = {n["id"]: n for n in self.client.get("/notes").json()}
        self.assertEqual(listed[new_id]["owner"], "alice")

    def test_creating_a_note_without_a_title_is_422(self):
        response = self.client.post("/notes", json={"body": "b"},
                                    headers=DEV)
        self.assertEqual(response.status_code, 422)
        self.assertIn("title", response.json()["error"]["message"])

    def test_the_reader_token_may_not_delete(self):
        response = self.client.delete("/notes/1", headers=READER)
        self.assertEqual(response.status_code, 403)

    def test_the_admin_token_may_delete(self):
        response = self.client.delete("/notes/2", headers=DEV)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/notes/2").status_code, 404)

    def test_deleting_without_a_token_is_401(self):
        self.assertEqual(self.client.delete("/notes/1").status_code, 401)


class TestMainModule(unittest.TestCase):
    def test_main_exposes_an_app(self):
        import main

        self.assertTrue(hasattr(main, "app"))
        client = TestClient(main.app)
        self.addCleanup(client.close)
        self.assertEqual(client.get("/notes").status_code, 200)


if __name__ == "__main__":
    unittest.main()
