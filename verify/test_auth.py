"""Static bearer-token authentication."""

import unittest

from baseapi.auth import ANONYMOUS, authenticate
from baseapi.errors import ApiError

TOKENS = {
    "dev-token": {"subject": "alice", "roles": ["admin"]},
    "svc-token": {"subject": "service", "roles": []},
}


class TestAnonymous(unittest.TestCase):
    def test_the_anonymous_identity_has_no_subject_and_no_roles(self):
        self.assertEqual(ANONYMOUS, {"subject": None, "roles": []})


class TestAuthenticate(unittest.TestCase):
    def test_accepts_a_known_bearer_token(self):
        identity = authenticate("Bearer dev-token", TOKENS)
        self.assertEqual(identity["subject"], "alice")
        self.assertEqual(identity["roles"], ["admin"])

    def test_the_scheme_is_case_insensitive(self):
        for header in ("bearer dev-token", "BEARER dev-token",
                       "BeArEr dev-token"):
            with self.subTest(header=header):
                self.assertEqual(
                    authenticate(header, TOKENS)["subject"], "alice")

    def test_extra_whitespace_around_the_token_is_tolerated(self):
        self.assertEqual(
            authenticate("Bearer   dev-token  ", TOKENS)["subject"], "alice")

    def test_the_token_value_itself_is_case_sensitive(self):
        with self.assertRaises(ApiError):
            authenticate("Bearer DEV-TOKEN", TOKENS)

    def test_returns_a_copy_so_the_config_cannot_be_mutated(self):
        identity = authenticate("Bearer dev-token", TOKENS)
        identity["roles"].append("root")
        identity["subject"] = "mallory"
        self.assertEqual(TOKENS["dev-token"],
                         {"subject": "alice", "roles": ["admin"]})


class TestRejection(unittest.TestCase):
    def assertUnauthorized(self, header, tokens=None):
        with self.assertRaises(ApiError) as caught:
            authenticate(header, TOKENS if tokens is None else tokens)
        self.assertEqual(caught.exception.status, 401)

    def test_a_missing_header_is_rejected(self):
        self.assertUnauthorized(None)

    def test_an_empty_header_is_rejected(self):
        self.assertUnauthorized("")
        self.assertUnauthorized("   ")

    def test_a_header_without_the_bearer_scheme_is_rejected(self):
        self.assertUnauthorized("dev-token")
        self.assertUnauthorized("Basic dev-token")
        self.assertUnauthorized("Token dev-token")

    def test_a_bearer_scheme_with_no_token_is_rejected(self):
        self.assertUnauthorized("Bearer")
        self.assertUnauthorized("Bearer ")

    def test_an_unknown_token_is_rejected(self):
        self.assertUnauthorized("Bearer nope")

    def test_no_configured_tokens_means_nothing_authenticates(self):
        self.assertUnauthorized("Bearer dev-token", tokens={})

    def test_the_message_does_not_echo_the_supplied_token(self):
        with self.assertRaises(ApiError) as caught:
            authenticate("Bearer super-secret-guess", TOKENS)
        self.assertNotIn("super-secret-guess", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
