"""Loading and validating app.yml and endpoints/*.yml."""

import os
import tempfile
import textwrap
import unittest

from baseapi.config import load_app, load_endpoint
from baseapi.errors import ConfigError


def endpoint_data(**overrides):
    """A minimal valid endpoint, with fields replaced or removed."""
    data = {
        "name": "get_note",
        "method": "GET",
        "path": "/notes/{note_id}",
        "params": {"note_id": {"in": "path", "type": "int", "required": True}},
        "query": {
            "sql": "SELECT id, title FROM notes WHERE id = :note_id",
            "returns": "one",
        },
    }
    for key, value in overrides.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


class TestEndpointHappyPath(unittest.TestCase):
    def test_loads_the_minimal_endpoint(self):
        ep = load_endpoint(endpoint_data())
        self.assertEqual(ep.name, "get_note")
        self.assertEqual(ep.method, "GET")
        self.assertEqual(ep.path, "/notes/{note_id}")
        self.assertEqual(ep.query.sql,
                         "SELECT id, title FROM notes WHERE id = :note_id")
        self.assertEqual(ep.query.returns, "one")

    def test_optional_sections_get_defaults(self):
        ep = load_endpoint(endpoint_data())
        self.assertEqual(ep.summary, "")
        self.assertEqual(ep.auth, "none")
        self.assertEqual(ep.checks, [])
        self.assertEqual(ep.response.status, 200)
        self.assertEqual(ep.response.when_empty, 404)
        self.assertIsNone(ep.response.transform)
        self.assertIsNone(ep.response.fields)

    def test_the_method_is_normalised_to_upper_case(self):
        ep = load_endpoint(endpoint_data(method="get"))
        self.assertEqual(ep.method, "GET")

    def test_every_supported_method_is_accepted(self):
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                ep = load_endpoint(endpoint_data(
                    method=method,
                    params={"note_id": {"in": "path", "type": "int",
                                        "required": True}},
                ))
                self.assertEqual(ep.method, method)

    def test_summary_and_auth_are_read(self):
        ep = load_endpoint(endpoint_data(summary="Get one.", auth="required"))
        self.assertEqual(ep.summary, "Get one.")
        self.assertEqual(ep.auth, "required")


class TestParamSpecs(unittest.TestCase):
    def test_reads_location_type_and_requiredness(self):
        ep = load_endpoint(endpoint_data(
            path="/notes",
            params={"q": {"in": "query", "type": "str", "required": True}},
            query={"sql": "SELECT id FROM notes WHERE title = :q",
                   "returns": "many"},
        ))
        spec = ep.params["q"]
        self.assertEqual(spec.name, "q")
        self.assertEqual(spec.location, "query")
        self.assertEqual(spec.type, "str")
        self.assertTrue(spec.required)

    def test_required_defaults_to_false(self):
        ep = load_endpoint(endpoint_data(
            path="/notes",
            params={"q": {"in": "query", "type": "str"}},
            query={"sql": "SELECT id FROM notes WHERE title = :q",
                   "returns": "many"},
        ))
        self.assertFalse(ep.params["q"].required)
        self.assertFalse(ep.params["q"].has_default)

    def test_a_declared_default_is_kept_including_falsy_values(self):
        ep = load_endpoint(endpoint_data(
            path="/notes",
            params={"verbose": {"in": "query", "type": "bool",
                                "default": False}},
            query={"sql": "SELECT id FROM notes", "returns": "many"},
        ))
        spec = ep.params["verbose"]
        self.assertTrue(spec.has_default)
        self.assertIs(spec.default, False)

    def test_every_supported_location_and_type(self):
        for location in ("query", "body", "header", "auth"):
            for type_name in ("str", "int", "float", "bool"):
                with self.subTest(location=location, type=type_name):
                    ep = load_endpoint(endpoint_data(
                        method="POST",
                        path="/notes",
                        params={"v": {"in": location, "type": type_name}},
                        query={"sql": "SELECT :v AS v", "returns": "one"},
                    ))
                    self.assertEqual(ep.params["v"].location, location)
                    self.assertEqual(ep.params["v"].type, type_name)


class TestEndpointValidation(unittest.TestCase):
    def assertRejects(self, data, hint=None):
        with self.assertRaises(ConfigError) as caught:
            load_endpoint(data)
        if hint:
            self.assertIn(hint, str(caught.exception))

    def test_rejects_a_missing_required_key(self):
        for key in ("name", "method", "path", "query"):
            with self.subTest(key=key):
                self.assertRejects(endpoint_data(**{key: None}))

    def test_rejects_an_unknown_top_level_key(self):
        self.assertRejects(endpoint_data(cheks=[]), hint="cheks")

    def test_rejects_an_unknown_param_key(self):
        self.assertRejects(endpoint_data(
            params={"note_id": {"in": "path", "type": "int",
                                "requried": True}},
        ), hint="requried")

    def test_rejects_an_unknown_query_key(self):
        self.assertRejects(endpoint_data(query={
            "sql": "SELECT 1 AS n", "returns": "one", "timeout": 5,
        }), hint="timeout")

    def test_rejects_an_unknown_response_key(self):
        self.assertRejects(endpoint_data(response={"stauts": 201}),
                           hint="stauts")

    def test_rejects_an_unsupported_method(self):
        self.assertRejects(endpoint_data(method="OPTIONS"))
        self.assertRejects(endpoint_data(method="FETCH"))

    def test_rejects_a_path_without_a_leading_slash(self):
        self.assertRejects(endpoint_data(path="notes", params={},
                                         query={"sql": "SELECT 1 AS n",
                                                "returns": "one"}))

    def test_rejects_a_path_placeholder_with_no_declared_parameter(self):
        self.assertRejects(endpoint_data(
            params={},
            query={"sql": "SELECT 1 AS n", "returns": "one"},
        ), hint="note_id")

    def test_rejects_a_path_parameter_missing_from_the_path(self):
        self.assertRejects(endpoint_data(
            path="/notes",
            params={"note_id": {"in": "path", "type": "int"}},
            query={"sql": "SELECT 1 AS n", "returns": "one"},
        ), hint="note_id")

    def test_rejects_a_sql_parameter_that_was_never_declared(self):
        self.assertRejects(endpoint_data(
            query={"sql": "SELECT id FROM notes WHERE id = :note_uid",
                   "returns": "one"},
        ), hint="note_uid")

    def test_rejects_a_body_parameter_on_a_get(self):
        self.assertRejects(endpoint_data(
            path="/notes",
            params={"title": {"in": "body", "type": "str"}},
            query={"sql": "SELECT :title AS t", "returns": "one"},
        ), hint="body")

    def test_rejects_a_body_parameter_on_a_delete(self):
        self.assertRejects(endpoint_data(
            method="DELETE",
            path="/notes",
            params={"title": {"in": "body", "type": "str"}},
            query={"sql": "DELETE FROM notes WHERE title = :title",
                   "returns": "none"},
        ), hint="body")

    def test_rejects_an_unknown_param_location(self):
        self.assertRejects(endpoint_data(
            path="/notes",
            params={"q": {"in": "cookie", "type": "str"}},
            query={"sql": "SELECT :q AS q", "returns": "one"},
        ), hint="cookie")

    def test_rejects_an_unknown_param_type(self):
        self.assertRejects(endpoint_data(
            params={"note_id": {"in": "path", "type": "integer"}},
        ), hint="integer")

    def test_rejects_an_unknown_returns_mode(self):
        self.assertRejects(endpoint_data(query={
            "sql": "SELECT 1 AS n", "returns": "single",
        }), hint="single")

    def test_rejects_a_missing_sql(self):
        self.assertRejects(endpoint_data(query={"returns": "one"}))

    def test_rejects_when_empty_unless_returns_is_one(self):
        for mode in ("many", "none"):
            with self.subTest(returns=mode):
                self.assertRejects(endpoint_data(
                    query={"sql": "SELECT id FROM notes WHERE id = :note_id",
                           "returns": mode},
                    response={"when_empty": 404},
                ), hint="when_empty")

    def test_rejects_an_unknown_auth_mode(self):
        self.assertRejects(endpoint_data(auth="optional"), hint="optional")

    def test_rejects_a_bad_expression_in_a_check(self):
        self.assertRejects(endpoint_data(checks=[
            {"when": "request.id == 1", "status": 400, "message": "no"},
        ]), hint="request")

    def test_rejects_a_bad_expression_in_a_response_field(self):
        self.assertRejects(endpoint_data(
            response={"fields": {"id": "rows.id["}},
        ))

    def test_rejects_a_check_with_neither_when_nor_hook(self):
        self.assertRejects(endpoint_data(checks=[
            {"status": 400, "message": "no"},
        ]))

    def test_rejects_a_check_with_both_when_and_hook(self):
        self.assertRejects(endpoint_data(checks=[
            {"when": "params.note_id > 0", "hook": "hooks:f",
             "status": 400, "message": "no"},
        ]))

    def test_rejects_a_malformed_hook_reference(self):
        for ref in ("hooks.can_read", "hooks:", ":can_read", "can_read"):
            with self.subTest(ref=ref):
                self.assertRejects(endpoint_data(checks=[{"hook": ref}]))

    def test_rejects_a_malformed_transform_reference(self):
        self.assertRejects(endpoint_data(response={"transform": "hooks"}))


class TestNonStringScalars(unittest.TestCase):
    """YAML happily produces bools and ints where a string was meant.
    Every one of those must come back as a ConfigError, never as a raw
    TypeError or AttributeError from deep inside the parser."""

    def assertConfigError(self, data):
        with self.assertRaises(ConfigError):
            load_endpoint(data)

    def test_a_non_string_name(self):
        self.assertConfigError(endpoint_data(name=123))

    def test_a_non_string_method(self):
        self.assertConfigError(endpoint_data(method=123))

    def test_a_non_string_path(self):
        self.assertConfigError(endpoint_data(
            path=123, params={},
            query={"sql": "SELECT 1 AS n", "returns": "one"}))

    def test_a_non_string_summary(self):
        self.assertConfigError(endpoint_data(summary=123))

    def test_a_non_string_sql(self):
        self.assertConfigError(endpoint_data(
            query={"sql": 123, "returns": "one"}))

    def test_a_non_string_returns(self):
        self.assertConfigError(endpoint_data(
            query={"sql": "SELECT 1 AS n", "returns": 1}))

    def test_a_boolean_when_expression(self):
        # `when: true` is an easy slip: YAML turns it into a bool, and the
        # tokenizer must not be handed a non-string.
        self.assertConfigError(endpoint_data(checks=[
            {"when": True, "status": 400, "message": "no"}]))

    def test_a_numeric_when_expression(self):
        self.assertConfigError(endpoint_data(checks=[
            {"when": 1, "status": 400, "message": "no"}]))

    def test_a_non_string_hook_reference(self):
        self.assertConfigError(endpoint_data(checks=[
            {"hook": 123, "status": 400, "message": "no"}]))

    def test_a_non_integer_check_status(self):
        self.assertConfigError(endpoint_data(checks=[
            {"when": "params.note_id > 0", "status": "400"}]))

    def test_a_non_string_check_message(self):
        self.assertConfigError(endpoint_data(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": 5}]))

    def test_a_non_string_response_field_expression(self):
        self.assertConfigError(endpoint_data(
            response={"fields": {"id": True}}))

    def test_a_non_string_transform_reference(self):
        self.assertConfigError(endpoint_data(response={"transform": 5}))

    def test_a_non_integer_response_status(self):
        self.assertConfigError(endpoint_data(response={"status": "200"}))

    def test_a_non_integer_when_empty(self):
        self.assertConfigError(endpoint_data(response={"when_empty": "404"}))

    def test_a_boolean_is_not_an_integer_status(self):
        # YAML `true` is an int subclass in Python; every status field must
        # reject it, not quietly use True as an HTTP status code.
        self.assertConfigError(endpoint_data(response={"when_empty": True}))
        self.assertConfigError(endpoint_data(response={"status": True}))
        self.assertConfigError(endpoint_data(checks=[
            {"when": "params.note_id > 0", "status": True}]))

    def test_a_non_string_param_location_or_type(self):
        self.assertConfigError(endpoint_data(
            params={"note_id": {"in": 1, "type": "int"}}))
        self.assertConfigError(endpoint_data(
            params={"note_id": {"in": "path", "type": 1}}))

    def test_a_non_boolean_required_flag(self):
        self.assertConfigError(endpoint_data(
            params={"note_id": {"in": "path", "type": "int",
                                "required": "yes"}}))

    def test_a_section_that_should_be_a_mapping_but_is_not(self):
        self.assertConfigError(endpoint_data(params=["note_id"]))
        self.assertConfigError(endpoint_data(query="SELECT 1"))
        self.assertConfigError(endpoint_data(response=["status"]))

    def test_checks_that_are_not_a_list_of_mappings(self):
        self.assertConfigError(endpoint_data(checks={"when": "true"}))
        self.assertConfigError(endpoint_data(checks=["params.note_id > 0"]))

    def test_the_whole_document_not_being_a_mapping(self):
        for data in ([1, 2], "text", 7, None):
            with self.subTest(data=data):
                self.assertConfigError(data)


class TestChecks(unittest.TestCase):
    def test_checks_keep_their_file_order(self):
        ep = load_endpoint(endpoint_data(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": "first"},
            {"when": "params.note_id < 99", "status": 403, "message": "second"},
        ]))
        self.assertEqual([c.message for c in ep.checks], ["first", "second"])
        self.assertEqual([c.status for c in ep.checks], [400, 403])

    def test_an_expression_check_is_compiled_to_a_callable(self):
        ep = load_endpoint(endpoint_data(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": "no"},
        ]))
        check = ep.checks[0]
        self.assertIsNone(check.hook)
        self.assertIs(check.expression({"params": {"note_id": 1}}), True)
        self.assertIs(check.expression({"params": {"note_id": 0}}), False)

    def test_a_hook_check_keeps_the_reference_and_has_no_expression(self):
        ep = load_endpoint(endpoint_data(checks=[
            {"hook": "hooks:can_read", "status": 403, "message": "no"},
        ]))
        check = ep.checks[0]
        self.assertEqual(check.hook, "hooks:can_read")
        self.assertIsNone(check.expression)

    def test_status_and_message_have_defaults(self):
        ep = load_endpoint(endpoint_data(checks=[
            {"when": "params.note_id > 0"},
        ]))
        self.assertEqual(ep.checks[0].status, 400)
        self.assertEqual(ep.checks[0].message, "check failed")


class TestLoadApp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        os.makedirs(os.path.join(self.dir, "endpoints"))

    def write(self, relative_path, text):
        full = os.path.join(self.dir, relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(text).lstrip("\n"))

    def write_endpoint(self, filename, name, method="GET", path="/notes"):
        self.write("endpoints/" + filename, f"""
            name: {name}
            method: {method}
            path: {path}
            query:
              sql: "SELECT id FROM notes"
              returns: many
        """)

    def test_loads_database_and_endpoints(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///notes.db"
        """)
        self.write_endpoint("a.yml", "list_notes")
        app = load_app(self.dir)
        self.assertEqual(app.database_url, "sqlite:///notes.db")
        self.assertEqual([e.name for e in app.endpoints], ["list_notes"])
        self.assertEqual(app.base_dir, self.dir)
        self.assertEqual(app.tokens, {})
        self.assertIsNone(app.init_sql)

    def test_endpoints_are_loaded_in_a_stable_alphabetical_order(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write_endpoint("b.yml", "b_ep", path="/b")
        self.write_endpoint("a.yml", "a_ep", path="/a")
        self.write_endpoint("c.yml", "c_ep", path="/c")
        app = load_app(self.dir)
        self.assertEqual([e.name for e in app.endpoints],
                         ["a_ep", "b_ep", "c_ep"])

    def test_reads_yaml_and_yml_extensions(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write_endpoint("a.yml", "a_ep", path="/a")
        self.write_endpoint("b.yaml", "b_ep", path="/b")
        app = load_app(self.dir)
        self.assertEqual(len(app.endpoints), 2)

    def test_an_empty_endpoints_directory_is_allowed(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.assertEqual(load_app(self.dir).endpoints, [])

    def test_init_sql_is_read_as_text(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
              init_sql: "schema.sql"
        """)
        self.write("schema.sql", "CREATE TABLE notes (id INTEGER);\n")
        app = load_app(self.dir)
        self.assertIn("CREATE TABLE notes", app.init_sql)

    def test_a_missing_init_sql_file_is_a_config_error(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
              init_sql: "nope.sql"
        """)
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_tokens_are_indexed_by_their_literal_value(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token: "dev-token"
                  subject: "alice"
                  roles: ["admin", "staff"]
        """)
        app = load_app(self.dir)
        self.assertEqual(app.tokens, {
            "dev-token": {"subject": "alice", "roles": ["admin", "staff"]},
        })

    def test_roles_default_to_an_empty_list(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token: "t"
                  subject: "alice"
        """)
        self.assertEqual(load_app(self.dir).tokens["t"]["roles"], [])

    def test_token_env_is_resolved_from_the_environment(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token_env: "BASEAPI_TEST_TOKEN"
                  subject: "service"
        """)
        os.environ["BASEAPI_TEST_TOKEN"] = "secret-value"
        self.addCleanup(os.environ.pop, "BASEAPI_TEST_TOKEN", None)
        app = load_app(self.dir)
        self.assertEqual(app.tokens["secret-value"]["subject"], "service")

    def test_an_unset_token_env_is_a_config_error(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token_env: "BASEAPI_DEFINITELY_UNSET"
                  subject: "service"
        """)
        os.environ.pop("BASEAPI_DEFINITELY_UNSET", None)
        with self.assertRaises(ConfigError) as caught:
            load_app(self.dir)
        self.assertIn("BASEAPI_DEFINITELY_UNSET", str(caught.exception))

    def test_a_token_with_neither_token_nor_token_env_is_rejected(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - subject: "alice"
        """)
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_a_token_with_both_token_and_token_env_is_rejected(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token: "t"
                  token_env: "E"
                  subject: "alice"
        """)
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_a_token_needs_a_subject(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token: "t"
        """)
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_rejects_duplicate_endpoint_names(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write_endpoint("a.yml", "same", path="/a")
        self.write_endpoint("b.yml", "same", path="/b")
        with self.assertRaises(ConfigError) as caught:
            load_app(self.dir)
        self.assertIn("same", str(caught.exception))

    def test_rejects_a_duplicate_method_and_path_pair(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write_endpoint("a.yml", "one", method="GET", path="/notes")
        self.write_endpoint("b.yml", "two", method="GET", path="/notes")
        with self.assertRaises(ConfigError) as caught:
            load_app(self.dir)
        message = str(caught.exception)
        self.assertIn("/notes", message)
        self.assertIn("GET", message)

    def test_the_same_path_with_different_methods_is_fine(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write_endpoint("a.yml", "one", method="GET", path="/notes")
        self.write("endpoints/b.yml", """
            name: two
            method: DELETE
            path: /notes
            query:
              sql: "DELETE FROM notes"
              returns: none
        """)
        self.assertEqual(len(load_app(self.dir).endpoints), 2)

    def test_a_missing_app_yml_is_a_config_error(self):
        self.write_endpoint("a.yml", "a_ep")
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_a_missing_endpoints_directory_is_a_config_error(self):
        os.rmdir(os.path.join(self.dir, "endpoints"))
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_a_missing_directory_is_a_config_error(self):
        with self.assertRaises(ConfigError):
            load_app(os.path.join(self.dir, "nope"))

    def test_broken_yaml_is_a_config_error_naming_the_file(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write("endpoints/broken.yml", "name: [unclosed\n")
        with self.assertRaises(ConfigError) as caught:
            load_app(self.dir)
        self.assertIn("broken.yml", str(caught.exception))

    def test_an_invalid_endpoint_error_names_its_file(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write("endpoints/bad.yml", """
            name: bad
            method: GET
            path: /bad
            query:
              sql: "SELECT id FROM notes"
              returns: sometimes
        """)
        with self.assertRaises(ConfigError) as caught:
            load_app(self.dir)
        self.assertIn("bad.yml", str(caught.exception))

    def test_an_endpoint_file_that_is_not_a_mapping_is_a_config_error(self):
        self.write("app.yml", 'database:\n  url: "sqlite:///:memory:"\n')
        self.write("endpoints/bad.yml", "- just\n- a\n- list\n")
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_a_missing_database_section_is_a_config_error(self):
        self.write("app.yml", "auth:\n  tokens: []\n")
        self.write_endpoint("a.yml", "a_ep")
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_a_non_string_database_url_is_a_config_error(self):
        # This one must not be allowed to slip through to db.connect: T9
        # requires every configuration failure to surface from create_app.
        for value in ("123", "true", "[a, b]", "null"):
            with self.subTest(value=value):
                self.write("app.yml", "database:\n  url: %s\n" % value)
                self.write_endpoint("a.yml", "a_ep")
                with self.assertRaises(ConfigError):
                    load_app(self.dir)

    def test_a_non_string_init_sql_is_a_config_error(self):
        for value in ("123", "true", "[a, b]"):
            with self.subTest(value=value):
                self.write("app.yml",
                           'database:\n  url: "sqlite:///:memory:"\n'
                           "  init_sql: %s\n" % value)
                self.write_endpoint("a.yml", "a_ep")
                with self.assertRaises(ConfigError):
                    load_app(self.dir)

    def test_a_non_string_token_is_a_config_error(self):
        for value in ("123", "true", "null", "[a]"):
            with self.subTest(value=value):
                self.write("app.yml",
                           'database:\n  url: "sqlite:///:memory:"\n'
                           "auth:\n  tokens:\n"
                           "    - token: %s\n"
                           '      subject: "alice"\n' % value)
                self.write_endpoint("a.yml", "a_ep")
                with self.assertRaises(ConfigError):
                    load_app(self.dir)

    def test_a_null_token_never_becomes_the_string_none(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token: null
                  subject: "alice"
        """)
        self.write_endpoint("a.yml", "a_ep")
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_a_non_string_token_env_is_a_config_error(self):
        for value in ("123", "true", "[a]"):
            with self.subTest(value=value):
                self.write("app.yml",
                           'database:\n  url: "sqlite:///:memory:"\n'
                           "auth:\n  tokens:\n"
                           "    - token_env: %s\n"
                           '      subject: "alice"\n' % value)
                self.write_endpoint("a.yml", "a_ep")
                with self.assertRaises(ConfigError):
                    load_app(self.dir)

    def test_a_non_string_subject_is_a_config_error(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token: "t"
                  subject: 5
        """)
        self.write_endpoint("a.yml", "a_ep")
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_roles_must_be_a_list_of_strings(self):
        # `roles: "admin"` would make `'admin' in auth.roles` a substring
        # match, so a role named "adm" would pass an admin-only check.
        for value in ('"admin"', "5", "true", "[1, 2]", "{a: b}"):
            with self.subTest(value=value):
                self.write("app.yml",
                           'database:\n  url: "sqlite:///:memory:"\n'
                           "auth:\n  tokens:\n"
                           '    - token: "t"\n'
                           '      subject: "alice"\n'
                           "      roles: %s\n" % value)
                self.write_endpoint("a.yml", "a_ep")
                with self.assertRaises(ConfigError):
                    load_app(self.dir)

    def test_a_valid_roles_list_still_loads(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            auth:
              tokens:
                - token: "t"
                  subject: "alice"
                  roles: ["admin", "staff"]
        """)
        self.write_endpoint("a.yml", "a_ep")
        self.assertEqual(load_app(self.dir).tokens["t"]["roles"],
                         ["admin", "staff"])

    def test_sections_that_should_be_mappings_or_lists_but_are_not(self):
        for body in ("database: 5\n",
                     'database:\n  url: "sqlite:///:memory:"\nauth: 5\n',
                     'database:\n  url: "sqlite:///:memory:"\n'
                     "auth:\n  tokens: 5\n",
                     'database:\n  url: "sqlite:///:memory:"\n'
                     "auth:\n  tokens:\n    - 5\n"):
            with self.subTest(body=body):
                self.write("app.yml", body)
                self.write_endpoint("a.yml", "a_ep")
                with self.assertRaises(ConfigError):
                    load_app(self.dir)

    def test_an_app_yml_that_is_not_a_mapping_is_a_config_error(self):
        self.write("app.yml", "- just\n- a\n- list\n")
        self.write_endpoint("a.yml", "a_ep")
        with self.assertRaises(ConfigError):
            load_app(self.dir)

    def test_rejects_an_unknown_app_yml_key(self):
        self.write("app.yml", """
            database:
              url: "sqlite:///:memory:"
            databse:
              url: "oops"
        """)
        self.write_endpoint("a.yml", "a_ep")
        with self.assertRaises(ConfigError) as caught:
            load_app(self.dir)
        self.assertIn("databse", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
