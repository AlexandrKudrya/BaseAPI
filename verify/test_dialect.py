"""Named SQL parameters: discovery and conversion to the pyformat style."""

import unittest

from baseapi.dialect import param_names, to_pyformat


class TestParamNames(unittest.TestCase):
    def test_no_parameters(self):
        self.assertEqual(param_names("SELECT 1"), [])

    def test_finds_one(self):
        self.assertEqual(
            param_names("SELECT * FROM notes WHERE id = :note_id"),
            ["note_id"],
        )

    def test_finds_several_in_order_of_first_appearance(self):
        sql = "INSERT INTO notes (title, body) VALUES (:title, :body)"
        self.assertEqual(param_names(sql), ["title", "body"])

    def test_deduplicates_repeated_names(self):
        sql = "SELECT * FROM t WHERE a = :x OR b = :x"
        self.assertEqual(param_names(sql), ["x"])

    def test_parameter_directly_after_an_equals_sign(self):
        self.assertEqual(param_names("SELECT * FROM t WHERE a=:x"), ["x"])

    def test_ignores_a_colon_inside_a_single_quoted_string(self):
        sql = "SELECT * FROM t WHERE start = '12:30' AND id = :id"
        self.assertEqual(param_names(sql), ["id"])

    def test_ignores_a_colon_inside_a_double_quoted_identifier(self):
        sql = 'SELECT "weird:column" FROM t WHERE id = :id'
        self.assertEqual(param_names(sql), ["id"])

    def test_handles_a_doubled_quote_escape_inside_a_string(self):
        sql = "SELECT * FROM t WHERE s = 'it''s :not_a_param' AND id = :id"
        self.assertEqual(param_names(sql), ["id"])

    def test_ignores_a_postgres_cast(self):
        sql = "SELECT id::text FROM t WHERE id = :id"
        self.assertEqual(param_names(sql), ["id"])

    def test_cast_immediately_followed_by_a_parameter(self):
        sql = "SELECT * FROM t WHERE a::text = :val"
        self.assertEqual(param_names(sql), ["val"])

    def test_a_lone_colon_is_not_a_parameter(self):
        self.assertEqual(param_names("SELECT * FROM t WHERE a = : "), [])

    def test_a_colon_followed_by_a_digit_is_not_a_parameter(self):
        self.assertEqual(param_names("SELECT * FROM t WHERE a = :1"), [])

    def test_underscores_and_digits_are_allowed_inside_a_name(self):
        self.assertEqual(param_names("SELECT :_a1 , :b_2"), ["_a1", "b_2"])


class TestToPyformat(unittest.TestCase):
    def test_converts_a_parameter(self):
        self.assertEqual(
            to_pyformat("SELECT * FROM notes WHERE id = :note_id"),
            "SELECT * FROM notes WHERE id = %(note_id)s",
        )

    def test_converts_every_occurrence(self):
        self.assertEqual(
            to_pyformat("SELECT * FROM t WHERE a = :x OR b = :x"),
            "SELECT * FROM t WHERE a = %(x)s OR b = %(x)s",
        )

    def test_leaves_a_cast_alone(self):
        self.assertEqual(
            to_pyformat("SELECT id::text FROM t WHERE id = :id"),
            "SELECT id::text FROM t WHERE id = %(id)s",
        )

    def test_leaves_string_literals_alone(self):
        self.assertEqual(
            to_pyformat("SELECT * FROM t WHERE s = '12:30'"),
            "SELECT * FROM t WHERE s = '12:30'",
        )

    def test_doubles_a_literal_percent_sign(self):
        # psycopg reads % as the start of a placeholder, so every literal
        # percent has to be escaped or a LIKE pattern breaks the query.
        self.assertEqual(
            to_pyformat("SELECT * FROM t WHERE name LIKE '%abc%'"),
            "SELECT * FROM t WHERE name LIKE '%%abc%%'",
        )

    def test_doubles_a_percent_outside_a_string_too(self):
        self.assertEqual(
            to_pyformat("SELECT 10 % 3"),
            "SELECT 10 %% 3",
        )

    def test_percent_and_parameter_together(self):
        self.assertEqual(
            to_pyformat("SELECT * FROM t WHERE n LIKE '%' AND id = :id"),
            "SELECT * FROM t WHERE n LIKE '%%' AND id = %(id)s",
        )

    def test_untouched_when_there_is_nothing_to_convert(self):
        self.assertEqual(to_pyformat("SELECT 1"), "SELECT 1")


if __name__ == "__main__":
    unittest.main()
