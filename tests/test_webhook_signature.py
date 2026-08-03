"""Unit tests for `whatbot/ingress.py`'s signature/handshake validation.

Pure-function tests, no network and no FastAPI app involved — covers task
4.1: token inválido recusado, assinatura inválida recusada, assinatura
válida aceita.
"""

import hashlib
import hmac
import unittest

from whatbot.ingress import verify_handshake, verify_signature

SECRET = "s3cr3t"
BODY = b'{"object":"instagram","entry":[]}'


def _signature_for(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestVerifySignature(unittest.TestCase):
    def test_valid_signature_is_accepted(self):
        self.assertTrue(verify_signature(SECRET, BODY, _signature_for(BODY)))

    def test_missing_signature_is_rejected(self):
        self.assertFalse(verify_signature(SECRET, BODY, None))

    def test_missing_secret_is_rejected(self):
        self.assertFalse(verify_signature(None, BODY, _signature_for(BODY)))
        self.assertFalse(verify_signature("", BODY, _signature_for(BODY)))

    def test_malformed_header_is_rejected(self):
        self.assertFalse(verify_signature(SECRET, BODY, "not-a-signature"))
        self.assertFalse(verify_signature(SECRET, BODY, "sha1=deadbeef"))

    def test_signature_for_a_different_body_is_rejected(self):
        signature = _signature_for(BODY)
        tampered_body = BODY + b" "
        self.assertFalse(verify_signature(SECRET, tampered_body, signature))

    def test_signature_computed_over_reserialized_json_would_differ(self):
        """The exact reason design.md mandates comparing raw bytes: even
        semantically-identical JSON with different key order/spacing hashes
        differently, so validating against the *parsed-then-reserialized*
        body could reject a genuinely valid signature."""
        import json

        reserialized = json.dumps(json.loads(BODY), sort_keys=True).encode("utf-8")
        self.assertNotEqual(BODY, reserialized)
        signature = _signature_for(BODY)
        self.assertFalse(verify_signature(SECRET, reserialized, signature))

    def test_signature_check_uses_constant_time_comparison(self):
        """Not a timing side-channel test (would be flaky) — asserts the
        implementation is built on `hmac.compare_digest`, the mechanism that
        makes the check constant-time, per design.md."""
        import inspect

        source = inspect.getsource(verify_signature)
        self.assertIn("hmac.compare_digest", source)


class TestVerifyHandshake(unittest.TestCase):
    def test_matching_token_is_accepted(self):
        self.assertTrue(verify_handshake("subscribe", "tok123", "tok123"))

    def test_wrong_token_is_rejected(self):
        self.assertFalse(verify_handshake("subscribe", "wrong", "tok123"))

    def test_missing_token_is_rejected(self):
        self.assertFalse(verify_handshake("subscribe", None, "tok123"))

    def test_unconfigured_expected_token_never_matches(self):
        """An empty/unset `IG_WEBHOOK_VERIFY_TOKEN` must never accept any
        token — otherwise an unconfigured deployment would accept anything."""
        self.assertFalse(verify_handshake("subscribe", "tok123", None))
        self.assertFalse(verify_handshake("subscribe", "tok123", ""))

    def test_wrong_mode_is_rejected(self):
        self.assertFalse(verify_handshake("unsubscribe", "tok123", "tok123"))


if __name__ == "__main__":
    unittest.main()
