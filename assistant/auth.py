# -*- coding: utf-8 -*-
"""Shared OAuth 2.1 token verification for the Sewa Setu MCP servers.

The portal (``app/oauth.py``) is the authorization server. It signs RS256 JWTs
and publishes its public keys at ``/.well-known/jwks.json``. A token carries:

    iss    the portal's public base URL (PUBLIC_BASE_URL)
    sub    "citizen:<mobile>" or "officer:<username>"
    aud    the RFC 8707 resource the client asked for (normally this MCP server)
    scope  exactly one of "citizen" / "officer"
    role   the same value as scope
    exp    expiry, bounded by the sign-in session's absolute end
    iat, jti, client_id, kind ("access" | "program")

Each MCP server verifies every token itself: the RS256 signature against the
portal JWKS, then issuer, audience, expiry, scope and subject. Identity always
comes from the verified token, never from a tool argument.
"""

import os
import threading
import time

import jwt
import requests
from mcp.server.auth.provider import AccessToken

# The portal issues exactly these scopes, one per sign-in.
KNOWN_SCOPES = ("citizen", "officer")


class AuthError(Exception):
    """An authorization failure carrying an HTTP-shaped status.

    401 for a missing, malformed, expired, wrong-issuer or wrong-audience token;
    403 for a valid token that does not hold the scope/role this endpoint needs.
    """

    def __init__(self, message, status=401):
        super().__init__(message)
        self.message = message
        self.status = status


def issuer():
    """The portal's public base URL, as stamped into token ``iss`` claims."""
    return os.environ.get("OAUTH_ISSUER", "http://localhost:8000").rstrip("/")


def _jwks_url():
    explicit = os.environ.get("OAUTH_JWKS_URL")
    if explicit:
        return explicit.rstrip("/") + "/.well-known/jwks.json"
    return issuer() + "/.well-known/jwks.json"


def _jwks_ttl():
    try:
        return max(0, int(os.environ.get("OAUTH_JWKS_TTL", "300")))
    except ValueError:
        return 300


class _JwksCache:
    """Thread-safe, TTL-bounded cache of the portal's public keys."""

    def __init__(self):
        self._lock = threading.Lock()
        self._keys = []
        self._fetched_at = 0.0

    def keys(self, force=False):
        now = time.time()
        with self._lock:
            if not force and self._keys and now - self._fetched_at < _jwks_ttl():
                return self._keys
            response = requests.get(_jwks_url(), timeout=5)
            response.raise_for_status()
            self._keys = list(response.json().get("keys", []))
            self._fetched_at = now
            return self._keys


_JWKS = _JwksCache()


def _find_key(keys, kid):
    if kid:
        for key in keys:
            if key.get("kid") == kid:
                return key
        return None
    return keys[0] if keys else None


def _audience_variants(url):
    """URL forms a client might use as its RFC 8707 resource indicator.

    The SDK renders ``resource_server_url`` with a trailing slash, while the
    portal's issuer has none, so accept the URL both with and without a slash,
    plus the same server URL with the MCP path.
    """
    url = (url or "").rstrip("/")
    if not url:
        return set()
    return {url, url + "/", url + "/mcp"}


def accepted_audiences(resource_url):
    """Audiences accepted for this endpoint.

    The MCP client asks the portal for ``resource`` and that value becomes the
    token's ``aud``. We accept the endpoint's own public URL, the same URL with
    the MCP path, and the portal issuer (so long-lived program tokens, which
    default to the issuer, still work). ``MCP_AUDIENCE`` may override the set
    with a comma-separated list.
    """
    audiences = _audience_variants(resource_url) | _audience_variants(issuer())
    raw = os.environ.get("MCP_AUDIENCE", "").strip()
    if raw:
        override = set()
        for item in raw.split(","):
            override |= _audience_variants(item.strip())
        audiences = override | _audience_variants(resource_url)
    audiences.discard("")
    return audiences


def verify_token(token, resource_url, required_scope=None):
    """Verify a portal access token and return its claims.

    Raises :class:`AuthError` (401) when the token is missing, malformed,
    expired, or signed by another issuer/audience; (403) when it is valid but
    lacks the required scope.
    """
    if not token or not token.strip():
        raise AuthError("A bearer access token is required.", 401)

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("The access token is malformed.", 401) from exc

    jwk = _find_key(_JWKS.keys(), header.get("kid"))
    if jwk is None and header.get("kid"):
        # The portal may have rotated its key; refresh once before giving up.
        jwk = _find_key(_JWKS.keys(force=True), header.get("kid"))
    if jwk is None:
        raise AuthError("The access token was not signed by this portal.", 401)

    try:
        signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
    except Exception as exc:  # noqa: BLE001 - any unusable key is a 401
        raise AuthError("The portal signing key is unusable.", 401) from exc

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer(),
            audience=sorted(accepted_audiences(resource_url)),
            options={"require": ["exp", "iat", "iss", "sub", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("The access token has expired.", 401) from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("The access token was issued for another service.", 401) from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthError("The access token was issued by another portal.", 401) from exc
    except jwt.PyJWTError as exc:
        raise AuthError("The access token is invalid.", 401) from exc

    scope = claims.get("scope")
    role = claims.get("role")
    subject = claims.get("sub") or ""
    if scope not in KNOWN_SCOPES or role != scope or not subject.startswith(scope + ":"):
        raise AuthError("The access token grants an unusable role.", 403)
    if required_scope and scope != required_scope:
        raise AuthError("This endpoint accepts %s authorization only." % required_scope, 403)
    return claims


def bearer_token(request):
    """Return the bearer token from a Starlette request, or None."""
    header = request.headers.get("authorization", "") if request is not None else ""
    if not header.lower().startswith("bearer "):
        return None
    return header[7:].strip()


def authenticate(request, resource_url, required_scope):
    """Verify the request's bearer token and return its claims.

    Tools call this so identity is always derived from the token even though the
    MCP transport has already authenticated the connection.
    """
    token = bearer_token(request)
    if not token:
        raise AuthError("A %s access token is required." % required_scope, 401)
    return verify_token(token, resource_url, required_scope=required_scope)


class PortalTokenVerifier:
    """Transport-level verifier used by FastMCP.

    A token that fails signature/issuer/audience/expiry yields ``None``, which
    the bearer middleware turns into a 401. A valid token is returned with its
    scope attached so the endpoint's ``required_scopes`` can reject the wrong
    role with a 403.
    """

    def __init__(self, resource_url):
        self.resource_url = resource_url

    async def verify_token(self, token):
        try:
            claims = verify_token(token, self.resource_url)
        except AuthError:
            return None
        audience = claims.get("aud")
        return AccessToken(
            token=token,
            client_id=str(claims.get("client_id", "")),
            scopes=[claims["scope"]],
            expires_at=int(claims["exp"]) if claims.get("exp") else None,
            resource=audience if isinstance(audience, str) else self.resource_url,
        )
