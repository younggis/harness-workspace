"""Local OIDC provider for end-to-end verification (NOT for production).

Implements discovery, authorize (auto-approve), token (PKCE S256) and JWKS with
an ephemeral RS256 key. Used by scripts/oidc-e2e.ps1 to exercise the real portal
OIDC code path against a real HTTP IdP without external credentials.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from urllib.parse import urlencode

import jwt
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "http://127.0.0.1:9100"
CLIENT_ID = "harness"
REDIRECT_URI = "http://127.0.0.1:9101/api/auth/oidc/callback"
EMAIL = "oidc.e2e@example.com"

app = FastAPI(title="Harness Mock IdP")
private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
public_jwk["kid"] = "mock-key-1"
public_jwk["use"] = "sig"
public_jwk["alg"] = "RS256"
CODES: dict[str, dict] = {}


@app.get("/.well-known/openid-configuration")
def discovery():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
        "jwks_uri": ISSUER + "/jwks",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@app.get("/jwks")
def jwks():
    return {"keys": [public_jwk]}


@app.get("/authorize")
def authorize(request: Request):
    q = request.query_params
    assert q.get("response_type") == "code"
    assert q.get("client_id") == CLIENT_ID
    assert q.get("redirect_uri") == REDIRECT_URI
    assert q.get("code_challenge_method") == "S256"
    code = uuid.uuid4().hex
    CODES[code] = {
        "challenge": q.get("code_challenge"),
        "nonce": q.get("nonce"),
        "expires": time.time() + 300,
    }
    return RedirectResponse(REDIRECT_URI + "?" + urlencode({"code": code, "state": q.get("state")}))


@app.post("/token")
async def token(request: Request):
    form = await request.form()
    code = str(form.get("code", ""))
    rec = CODES.pop(code, None)
    if not rec or rec["expires"] < time.time():
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    import hashlib
    import base64
    expected = base64.urlsafe_b64encode(hashlib.sha256(
        str(form.get("code_verifier", "")).encode()).digest()).decode().rstrip("=")
    if expected != rec["challenge"]:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if str(form.get("client_id")) != CLIENT_ID or str(form.get("redirect_uri")) != REDIRECT_URI:
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    now = int(time.time())
    id_token = jwt.encode({
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "mock-user-1",
        "exp": now + 600, "iat": now, "nonce": rec["nonce"],
        "email": EMAIL, "name": "OIDC E2E User",
    }, private_key, algorithm="RS256", headers={"kid": "mock-key-1"})
    return {"access_token": "mock-access", "token_type": "Bearer", "id_token": id_token}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9100, log_level="warning")
