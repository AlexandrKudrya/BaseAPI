"""Turning query rows into the response body."""

import unittest

from baseapi.expr import parse
from baseapi.mapping import build_body


class TestReturnsOne(unittest.TestCase):
    def test_without_fields_the_row_passes_through_unchanged(self):
        row = {"id": 1, "title": "a"}
        body = build_body(None, {"row": row}, "one")
        self.assertEqual(body, {"id": 1, "title": "a"})

    def test_fields_rename_and_select(self):
        fields = {"id": parse("row.id"), "text": parse("row.body")}
        body = build_body(fields, {"row": {"id": 1, "body": "x", "secret": 9}},
                          "one")
        self.assertEqual(body, {"id": 1, "text": "x"})

    def test_a_field_may_be_a_literal(self):
        fields = {"kind": parse("'note'"), "id": parse("row.id")}
        body = build_body(fields, {"row": {"id": 1}}, "one")
        self.assertEqual(body, {"kind": "note", "id": 1})

    def test_a_field_may_read_other_roots(self):
        fields = {"who": parse("auth.subject"), "asked": parse("params.q")}
        context = {"row": {"id": 1}, "auth": {"subject": "alice"},
                   "params": {"q": "term"}}
        body = build_body(fields, context, "one")
        self.assertEqual(body, {"who": "alice", "asked": "term"})

    def test_a_missing_column_becomes_null(self):
        fields = {"id": parse("row.id"), "nope": parse("row.absent")}
        body = build_body(fields, {"row": {"id": 1}}, "one")
        self.assertEqual(body, {"id": 1, "nope": None})

    def test_fields_may_nest(self):
        fields = {
            "id": parse("row.id"),
            "author": {"name": parse("row.author_name"),
                       "email": parse("row.author_email")},
        }
        row = {"id": 1, "author_name": "alice", "author_email": "a@example.com"}
        body = build_body(fields, {"row": row}, "one")
        self.assertEqual(body, {
            "id": 1,
            "author": {"name": "alice", "email": "a@example.com"},
        })

    def test_fields_may_nest_two_levels_deep(self):
        fields = {"a": {"b": {"c": parse("row.v")}}}
        body = build_body(fields, {"row": {"v": 7}}, "one")
        self.assertEqual(body, {"a": {"b": {"c": 7}}})

    def test_field_order_follows_the_yaml_order(self):
        fields = {"z": parse("row.id"), "a": parse("row.id"),
                  "m": parse("row.id")}
        body = build_body(fields, {"row": {"id": 1}}, "one")
        self.assertEqual(list(body.keys()), ["z", "a", "m"])


class TestReturnsMany(unittest.TestCase):
    def test_without_fields_the_rows_pass_through_unchanged(self):
        rows = [{"id": 1}, {"id": 2}]
        self.assertEqual(build_body(None, {"rows": rows}, "many"), rows)

    def test_fields_are_applied_to_every_row(self):
        fields = {"id": parse("row.id"), "text": parse("row.body")}
        rows = [{"id": 1, "body": "a"}, {"id": 2, "body": "b"}]
        body = build_body(fields, {"rows": rows}, "many")
        self.assertEqual(body, [{"id": 1, "text": "a"},
                                {"id": 2, "text": "b"}])

    def test_no_rows_gives_an_empty_list(self):
        fields = {"id": parse("row.id")}
        self.assertEqual(build_body(fields, {"rows": []}, "many"), [])

    def test_each_item_sees_its_own_row_and_the_shared_context(self):
        fields = {"id": parse("row.id"), "who": parse("auth.subject")}
        context = {"rows": [{"id": 1}, {"id": 2}],
                   "auth": {"subject": "alice"}}
        body = build_body(fields, context, "many")
        self.assertEqual(body, [{"id": 1, "who": "alice"},
                                {"id": 2, "who": "alice"}])

    def test_the_outer_row_binding_does_not_leak_between_items(self):
        fields = {"id": parse("row.id")}
        context = {"rows": [{"id": 1}, {"id": 2}], "row": {"id": 99}}
        body = build_body(fields, context, "many")
        self.assertEqual(body, [{"id": 1}, {"id": 2}])


class TestReturnsNone(unittest.TestCase):
    def test_without_fields_the_row_count_is_reported(self):
        body = build_body(None, {"result": {"rowcount": 3}}, "none")
        self.assertEqual(body, {"rowcount": 3})

    def test_fields_may_read_the_row_count(self):
        fields = {"deleted": parse("result.rowcount")}
        body = build_body(fields, {"result": {"rowcount": 2}}, "none")
        self.assertEqual(body, {"deleted": 2})

    def test_fields_may_read_the_request_parameters(self):
        fields = {"id": parse("params.note_id"),
                  "deleted": parse("result.rowcount")}
        context = {"params": {"note_id": 5}, "result": {"rowcount": 1}}
        self.assertEqual(build_body(fields, context, "none"),
                         {"id": 5, "deleted": 1})


class TestPurity(unittest.TestCase):
    def test_the_source_rows_are_not_mutated(self):
        rows = [{"id": 1, "body": "a"}]
        fields = {"id": parse("row.id")}
        build_body(fields, {"rows": rows}, "many")
        self.assertEqual(rows, [{"id": 1, "body": "a"}])

    def test_pass_through_of_one_row_does_not_alias_the_caller_dict(self):
        row = {"id": 1}
        body = build_body(None, {"row": row}, "one")
        body["id"] = 999
        self.assertEqual(row, {"id": 1})


if __name__ == "__main__":
    unittest.main()
