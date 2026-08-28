"""The check expression language: parsing and evaluation."""

import unittest

from baseapi.errors import ConfigError
from baseapi.expr import parse


def ev(source, context=None):
    return parse(source)(context or {})


class TestLiterals(unittest.TestCase):
    def test_integers(self):
        self.assertEqual(ev("0"), 0)
        self.assertEqual(ev("42"), 42)

    def test_floats(self):
        self.assertEqual(ev("1.5"), 1.5)

    def test_strings_in_both_quote_styles(self):
        self.assertEqual(ev("'abc'"), "abc")
        self.assertEqual(ev('"abc"'), "abc")

    def test_string_may_contain_the_other_quote(self):
        self.assertEqual(ev("\"it's\""), "it's")

    def test_empty_string(self):
        self.assertEqual(ev("''"), "")

    def test_booleans_and_null(self):
        self.assertIs(ev("true"), True)
        self.assertIs(ev("false"), False)
        self.assertIsNone(ev("null"))


class TestPaths(unittest.TestCase):
    def test_reads_a_value_from_a_root(self):
        self.assertEqual(ev("params.age", {"params": {"age": 21}}), 21)

    def test_every_documented_root_is_accepted(self):
        for root in ("params", "auth", "row", "rows", "result"):
            with self.subTest(root=root):
                self.assertEqual(ev(root + ".x", {root: {"x": 7}}), 7)

    def test_missing_key_under_a_known_root_is_null(self):
        self.assertIsNone(ev("params.nope", {"params": {"age": 21}}))

    def test_missing_root_in_the_context_is_null(self):
        self.assertIsNone(ev("params.age", {}))

    def test_unknown_root_is_a_config_error_at_parse_time(self):
        with self.assertRaises(ConfigError):
            parse("request.age")
        with self.assertRaises(ConfigError):
            parse("os.environ")

    def test_a_bare_name_is_not_a_valid_expression(self):
        with self.assertRaises(ConfigError):
            parse("params")


class TestComparisons(unittest.TestCase):
    def test_equality(self):
        self.assertIs(ev("1 == 1"), True)
        self.assertIs(ev("1 == 2"), False)
        self.assertIs(ev("'a' != 'b'"), True)

    def test_ordering(self):
        ctx = {"params": {"age": 21}}
        self.assertIs(ev("params.age >= 18", ctx), True)
        self.assertIs(ev("params.age > 21", ctx), False)
        self.assertIs(ev("params.age <= 21", ctx), True)
        self.assertIs(ev("params.age < 18", ctx), False)

    def test_ordering_against_null_is_false_not_an_error(self):
        ctx = {"params": {}}
        for source in ("params.age > 1", "params.age < 1",
                       "params.age >= 1", "params.age <= 1"):
            with self.subTest(source=source):
                self.assertIs(ev(source, ctx), False)

    def test_equality_against_null_still_works(self):
        self.assertIs(ev("params.age == null", {"params": {}}), True)
        self.assertIs(ev("params.age != null", {"params": {"age": 1}}), True)

    def test_in_and_not_in(self):
        ctx = {"auth": {"roles": ["admin", "staff"]}}
        self.assertIs(ev("'admin' in auth.roles", ctx), True)
        self.assertIs(ev("'guest' in auth.roles", ctx), False)
        self.assertIs(ev("'guest' not in auth.roles", ctx), True)

    def test_in_against_null_is_false(self):
        self.assertIs(ev("'admin' in auth.roles", {"auth": {}}), False)

    def test_in_against_a_string_haystack(self):
        self.assertIs(ev("'ab' in params.s", {"params": {"s": "xaby"}}), True)


class TestBooleanOperators(unittest.TestCase):
    def test_and_or_not_return_real_booleans(self):
        self.assertIs(ev("true and true"), True)
        self.assertIs(ev("true and false"), False)
        self.assertIs(ev("false or true"), True)
        self.assertIs(ev("false or false"), False)
        self.assertIs(ev("not false"), True)
        self.assertIs(ev("not true"), False)

    def test_truthiness_of_non_boolean_values(self):
        self.assertIs(ev("not params.x", {"params": {"x": 0}}), True)
        self.assertIs(ev("not params.x", {"params": {"x": "s"}}), False)
        self.assertIs(ev("not params.x", {"params": {}}), True)

    def test_and_binds_tighter_than_or(self):
        # parsed as: false and (false or true) would be False;
        # correct grouping is (false and false) or true -> True
        self.assertIs(ev("false and false or true"), True)

    def test_not_binds_tighter_than_and(self):
        self.assertIs(ev("not false and true"), True)

    def test_not_binds_looser_than_comparison(self):
        # "not 1 == 2" must mean "not (1 == 2)"
        self.assertIs(ev("not 1 == 2"), True)

    def test_parentheses_override_precedence(self):
        self.assertIs(ev("false and (false or true)"), False)

    def test_a_realistic_compound_check(self):
        ctx = {"params": {"note_id": 5}, "auth": {"roles": ["admin"]}}
        source = "params.note_id > 0 and ('admin' in auth.roles or 'staff' in auth.roles)"
        self.assertIs(ev(source, ctx), True)


class TestShortCircuit(unittest.TestCase):
    def test_or_does_not_need_the_right_side_when_left_is_true(self):
        # params.n is null, so an ordering comparison on it is False, not an
        # error; this documents that the whole expression stays evaluable.
        self.assertIs(ev("true or params.n > 1", {"params": {}}), True)


class TestSyntaxErrors(unittest.TestCase):
    def test_rejects_malformed_input(self):
        for source in (
            "",
            "   ",
            "1 +",
            "1 + 1",
            "params.age >",
            "== 1",
            "(1 == 1",
            "1 == 1)",
            "params..age",
            "params.age == ",
            "'unterminated",
            "1 == 1 1",
            "and true",
        ):
            with self.subTest(source=source):
                with self.assertRaises(ConfigError):
                    parse(source)

    def test_rejects_chained_comparisons(self):
        # a hand-rolled parser that loops over comparison operators would
        # silently accept these; the grammar allows exactly one.
        for source in ("1 < 2 < 3",
                       "params.a == params.b == params.c",
                       "params.a > 1 >= 0",
                       "'a' in auth.roles in params.x"):
            with self.subTest(source=source):
                with self.assertRaises(ConfigError):
                    parse(source)

    def test_still_accepts_comparisons_joined_by_and(self):
        ctx = {"params": {"a": 2}}
        self.assertIs(ev("1 < params.a and params.a < 3", ctx), True)

    def test_rejects_function_calls_and_indexing(self):
        for source in ("len(params.name) > 0", "params.items[0] == 1",
                       "params.name.upper() == 'A'"):
            with self.subTest(source=source):
                with self.assertRaises(ConfigError):
                    parse(source)

    def test_rejects_arithmetic(self):
        for source in ("params.a + params.b > 1", "params.a * 2 == 4"):
            with self.subTest(source=source):
                with self.assertRaises(ConfigError):
                    parse(source)

    def test_error_message_mentions_the_source(self):
        with self.assertRaises(ConfigError) as caught:
            parse("request.id == 1")
        self.assertIn("request", str(caught.exception))


class TestReuse(unittest.TestCase):
    def test_a_parsed_expression_can_be_evaluated_many_times(self):
        f = parse("params.n > 10")
        self.assertIs(f({"params": {"n": 11}}), True)
        self.assertIs(f({"params": {"n": 1}}), False)
        self.assertIs(f({"params": {"n": 11}}), True)


if __name__ == "__main__":
    unittest.main()
