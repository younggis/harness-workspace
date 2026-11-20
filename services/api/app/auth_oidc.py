"""OIDC authorization-code + PKCE helpers.

Discovery, token exchange and id_token verification. No vendor SDK; only stdlib + httpx + PyJWT.
"""
from __future__ import annotations

import base64
import hashlib
import time
from urllib.parse import urlencode

import httpx
import jwt

_DISCOVERY_CACHE: dict[str, tuple[float, dict]] = {}


def enabled(issuer: str, client_id: str) -> bool:
    return bool(issuer and client_id)


def discovery(issuer: str) -> dict:
    now = time.time()
    cached = _DISCOVERY_CACHE.get(issuer)
    if cached and cached[0] > now - 600:
        return cached[1]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=10.0) as c:
        r = c.get(url)
        r.raise_for_status()
        doc = r.json()
    _DISCOVERY_CACHE[issuer] = (now, doc)
    return doc


def pkce(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(issuer: str, client_id: str, redirect_uri: str,
                  state: str, nonce: str, verifier: str) -> str:
    doc = discovery(issuer)
    params = {
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": pkce(verifier), "code_challenge_method": "S256",
    }
    return doc["authorization_endpoint"] + "?" + urlencode(params)


def exchange_code(issuer: str, client_id: str, client_secret: str, redirect_uri: str,
                  code: str, verifier: str) -> dict:
    doc = discovery(issuer)
    data = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": client_id, "code_verifier": verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret
    with httpx.Client(timeout=15.0) as c:
        r = c.post(doc["token_endpoint"], data=data)
        r.raise_for_status()
        return r.json()


def verify_id_token(issuer: str, client_id: str, id_token: str, nonce: str) -> dict:
    doc = discovery(issuer)
    jwks_uri = doc["jwks_uri"]
    with httpx.Client(timeout=10.0) as c:
        jwks = c.get(jwks_uri).json()
    header = jwt.get_unverified_header(id_token)
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if not key_data:
        raise ValueError("OIDC signing key not found")
    key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
    claims = jwt.decode(
        id_token, key, algorithms=["RS256"], audience=client_id, issuer=issuer,
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    if claims.get("nonce") != nonce:
        raise ValueError("OIDC nonce mismatch")
    return claims


def sign_state(value: str, key: str) -> str:
    import hmac
    mac = hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{mac}"


def verify_state(signed: str, key: str) -> str | None:
    import hmac
    if "." not in signed:
        return None
    value, mac = signed.rsplit(".", 1)
    expected = hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()
    return value if hmac.compare_digest(mac, expected) else None


def verify_state_rotated(signed: str, settings) -> str | None:
    """Accept state cookies signed with the current or (during rotation) previous key."""
    raw = verify_state(signed, settings.session_signing_key)
    if raw is None and settings.session_signing_key_previous:
        raw = verify_state(signed, settings.session_signing_key_previous)
    return raw
