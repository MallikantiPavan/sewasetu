"""Token-verification tests for the shared MCP auth layer.

These mint portal-style RS256 tokens with a throwaway key and point the auth
module at that key, so they need no running portal or database.
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).parents[1] / "assistant"))

import auth  # noqa: E402


class _FakeJwks:
    def __init__(self, jwk):
        self._jwk = jwk

    def keys(self, force=False):
        return [self._jwk]


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update({"kid": "testkid", "alg": "RS256", "use": "sig"})
        cls.issuer = "http://issuer.test"
        cls.resource = "http://mcp.test"

    def setUp(self):
        os.environ["OAUTH_ISSUER"] = self.issuer
        os.environ.pop("OAUTH_JWKS_URL", None)
        os.environ.pop("MCP_AUDIENCE", None)
        auth._JWKS = _FakeJwks(self.jwk)

    def token(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "sub": "citizen:9999999999",
            "aud": self.resource,
            "scope": "citizen",
            "role": "citizen",
            "client_id": "client-1",
            "iat": now,
            "exp": now + 300,
            "jti": "abc",
            "kind": "access",
        }
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "testkid"})

    def assert_status(self, token, status, required_scope=None):
        with self.assertRaises(auth.AuthError) as raised:
            auth.verify_token(token, self.resource, required_scope=required_scope)
        self.assertEqual(raised.exception.status, status)

    def test_valid_citizen_token(self):
        claims = auth.verify_token(self.token(), self.resource, required_scope="citizen")
        self.assertEqual(claims["sub"], "citizen:9999999999")

    def test_resource_with_trailing_slash_is_accepted(self):
        claims = auth.verify_token(
            self.token(aud=self.resource + "/"), self.resource, required_scope="citizen"
        )
        self.assertEqual(claims["aud"], self.resource + "/")

    def test_missing_token_is_unauthorized(self):
        self.assert_status("", 401)

    def test_malformed_token_is_unauthorized(self):
        self.assert_status("not-a-jwt", 401)

    def test_expired_token_is_unauthorized(self):
        self.assert_status(self.token(exp=int(time.time()) - 10), 401)

    def test_wrong_issuer_is_unauthorized(self):
        self.assert_status(self.token(iss="http://evil.test"), 401)

    def test_wrong_audience_is_unauthorized(self):
        self.assert_status(self.token(aud="http://other.test"), 401)

    def test_unknown_signing_key_is_unauthorized(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        foreign = jwt.encode(
            {"iss": self.issuer, "sub": "citizen:1", "aud": self.resource,
             "scope": "citizen", "role": "citizen", "iat": int(time.time()),
             "exp": int(time.time()) + 300},
            other, algorithm="RS256", headers={"kid": "other"},
        )
        self.assert_status(foreign, 401)

    def test_role_scope_mismatch_is_forbidden(self):
        self.assert_status(self.token(scope="officer", role="citizen"), 403)

    def test_subject_scope_mismatch_is_forbidden(self):
        self.assert_status(self.token(sub="officer:someone"), 403)

    def test_wrong_required_scope_is_forbidden(self):
        self.assert_status(self.token(), 403, required_scope="officer")

    def test_officer_token_denied_at_citizen_endpoint(self):
        token = self.token(sub="officer:admin", scope="officer", role="officer")
        self.assert_status(token, 403, required_scope="citizen")

    def test_program_token_with_issuer_audience_is_accepted(self):
        token = self.token(sub="officer:admin", scope="officer", role="officer",
                           aud=self.issuer, kind="program")
        claims = auth.verify_token(token, self.resource, required_scope="officer")
        self.assertEqual(claims["kind"], "program")


if __name__ == "__main__":
    unittest.main()
