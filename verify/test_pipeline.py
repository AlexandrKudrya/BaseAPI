"""The request executor: coercion -> checks -> query -> mapping -> response.

The database is a stand-in here; real drivers are covered by test_db.py.
"""

import unittest

from baseapi.config import load_endpoint
from baseapi.errors import ApiError, ConfigError
from baseapi.pipeline import coerce_params, handle


class FakeResult:
    def __init__(self, rows, rowcount):
        self.rows = rows
        self.rowcount = rowcount


class FakeDb:
    """Records what it was asked to run and replays a scripted result."""

    def __init__(self, rows=None, rowcount=None):
        self._rows = [] if rows is None else rows
        self._rowcount = len(self._rows) if rowcount is None else rowcount
        self.calls = []

    def run(self, sql, params):
        self.calls.append((sql, dict(params)))
        return FakeResult([dict(r) for r in self._rows], self._rowcount)


def make(**overrides):
    data = {
        "name": "get_note",
        "method": "GET",
        "path": "/notes/{note_id}",
        "params": {"note_id": {"in": "path", "type": "int", "required": True}},
        "query": {"sql": "SELECT id, body FROM notes WHERE id = :note_id",
                  "returns": "one"},
    }
    data.update(overrides)
    return load_endpoint(data)


# ---------------------------------------------------------------- coercion

def coerce(param_spec, **sources):
    """Coerce a single declared parameter and return the resulting dict."""
    endpoint = make(
        method="POST",
        path="/notes",
        params={"v": param_spec},
        query={"sql": "SELECT :v AS v", "returns": "one"},
    )
    return coerce_params(endpoint, **sources)


class TestCoerceInt(unittest.TestCase):
    def test_a_numeric_string_from_the_path_becomes_an_int(self):
        endpoint = make()
        self.assertEqual(coerce_params(endpoint, path={"note_id": "42"}),
                         {"note_id": 42})

    def test_a_negative_number(self):
        endpoint = make()
        self.assertEqual(coerce_params(endpoint, path={"note_id": "-3"}),
                         {"note_id": -3})

    def test_an_int_passes_through(self):
        endpoint = make()
        self.assertEqual(coerce_params(endpoint, path={"note_id": 42}),
                         {"note_id": 42})

    def test_a_non_numeric_string_is_a_422_naming_the_field(self):
        endpoint = make()
        with self.assertRaises(ApiError) as caught:
            coerce_params(endpoint, path={"note_id": "abc"})
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("note_id", caught.exception.message)

    def test_a_float_is_rejected(self):
        endpoint = make()
        with self.assertRaises(ApiError):
            coerce_params(endpoint, path={"note_id": 1.5})
        with self.assertRaises(ApiError):
            coerce_params(endpoint, path={"note_id": "1.5"})

    def test_a_boolean_is_not_accepted_as_an_int(self):
        endpoint = make()
        with self.assertRaises(ApiError):
            coerce_params(endpoint, path={"note_id": True})


class TestCoerceOtherTypes(unittest.TestCase):
    def test_bool_from_query_strings(self):
        spec = {"in": "query", "type": "bool"}
        for text in ("true", "TRUE", "1", "yes", "on"):
            with self.subTest(text=text):
                self.assertIs(coerce(spec, query={"v": text})["v"], True)
        for text in ("false", "FALSE", "0", "no", "off"):
            with self.subTest(text=text):
                self.assertIs(coerce(spec, query={"v": text})["v"], False)

    def test_bool_from_a_real_boolean_and_from_0_and_1(self):
        spec = {"in": "body", "type": "bool"}
        self.assertIs(coerce(spec, body={"v": True})["v"], True)
        self.assertIs(coerce(spec, body={"v": 1})["v"], True)
        self.assertIs(coerce(spec, body={"v": 0})["v"], False)

    def test_an_unrecognised_bool_is_a_422(self):
        with self.assertRaises(ApiError):
            coerce({"in": "query", "type": "bool"}, query={"v": "maybe"})

    def test_float_accepts_ints_floats_and_numeric_strings(self):
        spec = {"in": "query", "type": "float"}
        self.assertEqual(coerce(spec, query={"v": "1.5"})["v"], 1.5)
        self.assertEqual(coerce(spec, query={"v": 2})["v"], 2.0)
        self.assertEqual(coerce(spec, query={"v": 2.5})["v"], 2.5)
        with self.assertRaises(ApiError):
            coerce(spec, query={"v": "abc"})

    def test_str_accepts_text_and_stringifies_numbers(self):
        spec = {"in": "query", "type": "str"}
        self.assertEqual(coerce(spec, query={"v": "abc"})["v"], "abc")
        self.assertEqual(coerce(spec, query={"v": 7})["v"], "7")

    def test_str_rejects_a_boolean(self):
        with self.assertRaises(ApiError):
            coerce({"in": "body", "type": "str"}, body={"v": True})

    def test_an_empty_string_is_a_value_not_an_absence(self):
        spec = {"in": "query", "type": "str", "required": True}
        self.assertEqual(coerce(spec, query={"v": ""})["v"], "")


class TestCoerceSources(unittest.TestCase):
    def test_a_header_is_matched_case_insensitively(self):
        spec = {"in": "header", "type": "str"}
        self.assertEqual(
            coerce(spec, headers={"V": "x"})["v"], "x")

    def test_underscores_in_a_header_param_match_hyphens(self):
        endpoint = make(
            path="/notes",
            params={"x_trace_id": {"in": "header", "type": "str"}},
            query={"sql": "SELECT :x_trace_id AS t", "returns": "one"},
        )
        result = coerce_params(endpoint, headers={"X-Trace-Id": "abc"})
        self.assertEqual(result["x_trace_id"], "abc")

    def test_an_auth_parameter_takes_its_value_from_the_identity(self):
        endpoint = make(
            method="POST", path="/notes",
            params={"subject": {"in": "auth", "type": "str",
                                "required": True}},
            query={"sql": "INSERT INTO notes (owner) VALUES (:subject)",
                   "returns": "none"},
        )
        result = coerce_params(endpoint,
                               auth={"subject": "alice", "roles": ["admin"]})
        self.assertEqual(result, {"subject": "alice"})

    def test_a_required_auth_parameter_without_an_identity_is_422(self):
        endpoint = make(
            method="POST", path="/notes",
            params={"subject": {"in": "auth", "type": "str",
                                "required": True}},
            query={"sql": "INSERT INTO notes (owner) VALUES (:subject)",
                   "returns": "none"},
        )
        with self.assertRaises(ApiError) as caught:
            coerce_params(endpoint, auth={"subject": None, "roles": []})
        self.assertEqual(caught.exception.status, 422)

    def test_an_auth_parameter_reaches_the_query(self):
        endpoint = make(
            method="POST", path="/notes", auth="required",
            params={"title": {"in": "body", "type": "str", "required": True},
                    "subject": {"in": "auth", "type": "str",
                                "required": True}},
            query={"sql": "INSERT INTO notes (title, owner) "
                          "VALUES (:title, :subject)",
                   "returns": "none"},
        )
        db = FakeDb(rows=[], rowcount=1)
        handle(endpoint, db=db, body={"title": "hi"},
               auth={"subject": "alice", "roles": []})
        self.assertEqual(db.calls[0][1], {"title": "hi", "subject": "alice"})

    def test_a_header_parameter_survives_the_trip_through_handle(self):
        # coerce_params reads headers, but the value has to actually reach it
        # from handle, or `in: header` is documented and dead.
        endpoint = make(
            path="/notes",
            params={"x_trace_id": {"in": "header", "type": "str",
                                   "required": True}},
            query={"sql": "SELECT :x_trace_id AS t", "returns": "one"},
        )
        db = FakeDb(rows=[{"t": "abc"}])
        status, _ = handle(endpoint, db=db, headers={"X-Trace-Id": "abc"})
        self.assertEqual(status, 200)
        self.assertEqual(db.calls[0][1], {"x_trace_id": "abc"})

    def test_a_missing_required_header_is_422_through_handle(self):
        endpoint = make(
            path="/notes",
            params={"x_trace_id": {"in": "header", "type": "str",
                                   "required": True}},
            query={"sql": "SELECT :x_trace_id AS t", "returns": "one"},
        )
        status, body = handle(endpoint, db=FakeDb(), headers={})
        self.assertEqual(status, 422)
        self.assertIn("x_trace_id", body["error"]["message"])

    def test_a_body_parameter_is_read_from_the_body(self):
        endpoint = make(
            method="POST", path="/notes",
            params={"title": {"in": "body", "type": "str", "required": True}},
            query={"sql": "INSERT INTO notes (title) VALUES (:title)",
                   "returns": "none"},
        )
        self.assertEqual(coerce_params(endpoint, body={"title": "hi"}),
                         {"title": "hi"})

    def test_a_body_that_is_not_an_object_is_a_422(self):
        endpoint = make(
            method="POST", path="/notes",
            params={"title": {"in": "body", "type": "str", "required": True}},
            query={"sql": "INSERT INTO notes (title) VALUES (:title)",
                   "returns": "none"},
        )
        for bad in ([1, 2], "text", 7):
            with self.subTest(body=bad):
                with self.assertRaises(ApiError) as caught:
                    coerce_params(endpoint, body=bad)
                self.assertEqual(caught.exception.status, 422)

    def test_extra_unknown_keys_are_ignored(self):
        endpoint = make()
        self.assertEqual(
            coerce_params(endpoint, path={"note_id": "1"},
                          query={"junk": "x"}),
            {"note_id": 1},
        )

    def test_a_parameter_is_only_read_from_its_declared_location(self):
        endpoint = make()  # note_id is declared in: path
        with self.assertRaises(ApiError):
            coerce_params(endpoint, query={"note_id": "1"})


class TestCoerceMissingValues(unittest.TestCase):
    def test_a_missing_required_parameter_is_a_422_naming_it(self):
        endpoint = make()
        with self.assertRaises(ApiError) as caught:
            coerce_params(endpoint)
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("note_id", caught.exception.message)

    def test_an_explicit_null_counts_as_missing(self):
        endpoint = make()
        with self.assertRaises(ApiError):
            coerce_params(endpoint, path={"note_id": None})

    def test_an_absent_optional_parameter_with_a_default_uses_it(self):
        spec = {"in": "query", "type": "bool", "default": False}
        self.assertIs(coerce(spec, query={})["v"], False)

    def test_an_absent_optional_parameter_without_a_default_is_omitted(self):
        spec = {"in": "query", "type": "str"}
        self.assertEqual(coerce(spec, query={}), {})

    def test_a_supplied_value_wins_over_the_default(self):
        spec = {"in": "query", "type": "bool", "default": False}
        self.assertIs(coerce(spec, query={"v": "true"})["v"], True)


# ----------------------------------------------------------------- handle

class TestHandleHappyPath(unittest.TestCase):
    def test_returns_one_row_with_the_configured_status(self):
        endpoint = make()
        db = FakeDb(rows=[{"id": 1, "body": "hello"}])
        status, body = handle(endpoint, db=db, path={"note_id": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"id": 1, "body": "hello"})

    def test_passes_the_coerced_parameters_to_the_query(self):
        endpoint = make()
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        handle(endpoint, db=db, path={"note_id": "1"})
        sql, params = db.calls[0]
        self.assertEqual(sql, endpoint.query.sql)
        self.assertEqual(params, {"note_id": 1})

    def test_response_fields_are_applied(self):
        endpoint = make(response={"fields": {"id": "row.id",
                                             "text": "row.body"}})
        db = FakeDb(rows=[{"id": 1, "body": "hello", "secret": 9}])
        status, body = handle(endpoint, db=db, path={"note_id": "1"})
        self.assertEqual(body, {"id": 1, "text": "hello"})

    def test_a_custom_response_status(self):
        endpoint = make(
            method="POST", path="/notes",
            params={"title": {"in": "body", "type": "str", "required": True}},
            query={"sql": "INSERT INTO notes (title) VALUES (:title) "
                          "RETURNING id",
                   "returns": "one"},
            response={"status": 201, "fields": {"id": "row.id"}},
        )
        db = FakeDb(rows=[{"id": 7}])
        status, body = handle(endpoint, db=db, body={"title": "hi"})
        self.assertEqual(status, 201)
        self.assertEqual(body, {"id": 7})

    def test_returns_many_gives_a_list(self):
        endpoint = make(
            path="/notes", params={},
            query={"sql": "SELECT id FROM notes", "returns": "many"},
        )
        db = FakeDb(rows=[{"id": 1}, {"id": 2}])
        status, body = handle(endpoint, db=db)
        self.assertEqual(status, 200)
        self.assertEqual(body, [{"id": 1}, {"id": 2}])

    def test_returns_many_with_no_rows_is_an_empty_list_not_an_error(self):
        endpoint = make(
            path="/notes", params={},
            query={"sql": "SELECT id FROM notes", "returns": "many"},
        )
        status, body = handle(endpoint, db=FakeDb(rows=[]))
        self.assertEqual((status, body), (200, []))

    def test_returns_none_reports_the_row_count(self):
        endpoint = make(
            method="DELETE",
            query={"sql": "DELETE FROM notes WHERE id = :note_id",
                   "returns": "none"},
        )
        db = FakeDb(rows=[], rowcount=1)
        status, body = handle(endpoint, db=db, path={"note_id": "1"})
        self.assertEqual((status, body), (200, {"rowcount": 1}))

    def test_returns_one_takes_the_first_row_when_the_query_gives_several(self):
        endpoint = make()
        db = FakeDb(rows=[{"id": 1, "body": "a"}, {"id": 2, "body": "b"}])
        _, body = handle(endpoint, db=db, path={"note_id": "1"})
        self.assertEqual(body, {"id": 1, "body": "a"})


class TestHandleEmptyResult(unittest.TestCase):
    def test_returns_one_with_no_rows_uses_when_empty(self):
        endpoint = make()
        status, body = handle(endpoint, db=FakeDb(rows=[]),
                              path={"note_id": "1"})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], 404)

    def test_the_empty_result_message_is_the_documented_one(self):
        endpoint = make()
        _, body = handle(endpoint, db=FakeDb(rows=[]), path={"note_id": "1"})
        self.assertEqual(body["error"]["message"], "not found")

    def test_when_empty_can_be_overridden(self):
        endpoint = make(response={"when_empty": 204})
        status, _ = handle(endpoint, db=FakeDb(rows=[]),
                           path={"note_id": "1"})
        self.assertEqual(status, 204)


class TestHandleErrorShape(unittest.TestCase):
    def test_every_error_uses_the_same_body_shape(self):
        endpoint = make()
        status, body = handle(endpoint, db=FakeDb(), path={"note_id": "abc"})
        self.assertEqual(status, 422)
        self.assertEqual(set(body), {"error"})
        self.assertEqual(set(body["error"]), {"code", "message"})
        self.assertEqual(body["error"]["code"], 422)
        self.assertIsInstance(body["error"]["message"], str)

    def test_handle_never_raises_an_api_error(self):
        endpoint = make(auth="required")
        try:
            status, body = handle(endpoint, db=FakeDb())
        except ApiError:  # pragma: no cover - this is the failure being tested
            self.fail("handle must convert ApiError into a response")
        self.assertEqual(status, 401)


class TestHandleChecks(unittest.TestCase):
    def test_a_passing_check_lets_the_request_through(self):
        endpoint = make(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": "bad id"},
        ])
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        status, _ = handle(endpoint, db=db, path={"note_id": "1"})
        self.assertEqual(status, 200)

    def test_a_failing_check_returns_the_authors_status_and_message(self):
        endpoint = make(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": "bad id"},
        ])
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        status, body = handle(endpoint, db=db, path={"note_id": "0"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["message"], "bad id")

    def test_a_failing_check_stops_the_query_from_running(self):
        endpoint = make(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": "bad id"},
        ])
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        handle(endpoint, db=db, path={"note_id": "0"})
        self.assertEqual(db.calls, [])

    def test_the_first_failing_check_wins(self):
        endpoint = make(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": "first"},
            {"when": "params.note_id < 10", "status": 403, "message": "second"},
        ])
        status, body = handle(endpoint, db=FakeDb(), path={"note_id": "0"})
        self.assertEqual((status, body["error"]["message"]), (400, "first"))

    def test_a_later_check_still_runs_when_earlier_ones_pass(self):
        endpoint = make(checks=[
            {"when": "params.note_id > 0", "status": 400, "message": "first"},
            {"when": "params.note_id < 10", "status": 403, "message": "second"},
        ])
        status, body = handle(endpoint, db=FakeDb(), path={"note_id": "50"})
        self.assertEqual((status, body["error"]["message"]), (403, "second"))

    def test_checks_run_after_coercion_so_they_see_typed_values(self):
        endpoint = make(checks=[
            {"when": "params.note_id > 9", "status": 400, "message": "small"},
        ])
        # as a string, "10" > "9" would be false; as an int it is true
        db = FakeDb(rows=[{"id": 10, "body": "x"}])
        status, _ = handle(endpoint, db=db, path={"note_id": "10"})
        self.assertEqual(status, 200)

    def test_checks_can_read_the_authenticated_identity(self):
        endpoint = make(auth="required", checks=[
            {"when": "'admin' in auth.roles", "status": 403,
             "message": "admins only"},
        ])
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        allowed = {"subject": "alice", "roles": ["admin"]}
        denied = {"subject": "bob", "roles": ["guest"]}
        self.assertEqual(
            handle(endpoint, db=db, path={"note_id": "1"}, auth=allowed)[0],
            200)
        self.assertEqual(
            handle(endpoint, db=db, path={"note_id": "1"}, auth=denied)[0],
            403)


class TestHandleHooks(unittest.TestCase):
    def test_a_hook_check_receives_the_context_and_can_pass(self):
        endpoint = make(checks=[
            {"hook": "h:allow", "status": 403, "message": "no"},
        ])
        seen = []

        def allow(context):
            seen.append(context)
            return True

        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        status, _ = handle(endpoint, db=db, path={"note_id": "1"},
                           hooks={"h:allow": allow})
        self.assertEqual(status, 200)
        self.assertEqual(seen[0]["params"], {"note_id": 1})
        self.assertEqual(seen[0]["auth"], {"subject": None, "roles": []})

    def test_a_hook_returning_false_fails_the_check(self):
        endpoint = make(checks=[
            {"hook": "h:deny", "status": 403, "message": "denied"},
        ])
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        status, body = handle(endpoint, db=db, path={"note_id": "1"},
                              hooks={"h:deny": lambda ctx: False})
        self.assertEqual((status, body["error"]["message"]), (403, "denied"))
        self.assertEqual(db.calls, [])

    def test_hook_and_expression_checks_run_in_file_order(self):
        order = []
        endpoint = make(checks=[
            {"hook": "h:first", "status": 400, "message": "one"},
            {"when": "params.note_id > 99", "status": 401, "message": "two"},
            {"hook": "h:third", "status": 402, "message": "three"},
        ])

        def make_hook(label, verdict):
            def hook(context):
                order.append(label)
                return verdict
            return hook

        status, body = handle(
            endpoint, db=FakeDb(), path={"note_id": "1"},
            hooks={"h:first": make_hook("first", True),
                   "h:third": make_hook("third", True)},
        )
        self.assertEqual(order, ["first"])
        self.assertEqual((status, body["error"]["message"]), (401, "two"))

    def test_a_transform_hook_rewrites_the_body(self):
        endpoint = make(response={"transform": "h:wrap"})
        db = FakeDb(rows=[{"id": 1, "body": "x"}])

        def wrap(body, context):
            return {"data": body, "for": context["params"]["note_id"]}

        status, body = handle(endpoint, db=db, path={"note_id": "1"},
                              hooks={"h:wrap": wrap})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"data": {"id": 1, "body": "x"}, "for": 1})

    def test_a_transform_hook_does_not_run_when_a_check_fails(self):
        calls = []
        endpoint = make(
            checks=[{"when": "params.note_id > 5", "status": 400,
                     "message": "no"}],
            response={"transform": "h:wrap"},
        )

        def wrap(body, context):
            calls.append(body)
            return body

        handle(endpoint, db=FakeDb(), path={"note_id": "1"},
               hooks={"h:wrap": wrap})
        self.assertEqual(calls, [])

    def test_an_unregistered_hook_is_a_config_error(self):
        endpoint = make(checks=[
            {"hook": "h:missing", "status": 403, "message": "no"},
        ])
        with self.assertRaises(ConfigError):
            handle(endpoint, db=FakeDb(), path={"note_id": "1"}, hooks={})


class TestHandleAuth(unittest.TestCase):
    def test_auth_required_without_an_identity_is_401(self):
        endpoint = make(auth="required")
        status, body = handle(endpoint, db=FakeDb(), path={"note_id": "1"})
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], 401)

    def test_auth_required_does_not_run_the_query(self):
        endpoint = make(auth="required")
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        handle(endpoint, db=db, path={"note_id": "1"})
        self.assertEqual(db.calls, [])

    def test_auth_required_with_an_identity_proceeds(self):
        endpoint = make(auth="required")
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        status, _ = handle(endpoint, db=db, path={"note_id": "1"},
                           auth={"subject": "alice", "roles": []})
        self.assertEqual(status, 200)

    def test_an_open_endpoint_sees_the_anonymous_identity(self):
        endpoint = make(response={"fields": {"who": "auth.subject"}})
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        _, body = handle(endpoint, db=db, path={"note_id": "1"})
        self.assertEqual(body, {"who": None})

    def test_an_open_endpoint_still_uses_an_identity_when_one_is_given(self):
        endpoint = make(response={"fields": {"who": "auth.subject"}})
        db = FakeDb(rows=[{"id": 1, "body": "x"}])
        _, body = handle(endpoint, db=db, path={"note_id": "1"},
                         auth={"subject": "alice", "roles": []})
        self.assertEqual(body, {"who": "alice"})


class TestHandleOrdering(unittest.TestCase):
    def test_auth_is_checked_before_parameters_are_coerced(self):
        endpoint = make(auth="required")
        status, _ = handle(endpoint, db=FakeDb(), path={"note_id": "abc"})
        self.assertEqual(status, 401)

    def test_parameters_are_coerced_before_checks_run(self):
        endpoint = make(checks=[
            {"hook": "h:never", "status": 403, "message": "no"},
        ])

        def never(context):  # pragma: no cover - must not be reached
            raise AssertionError("checks ran despite a coercion failure")

        status, _ = handle(endpoint, db=FakeDb(), path={"note_id": "abc"},
                           hooks={"h:never": never})
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()
