"""Password hashing, token hashing, CSRF and request signing primitives.

Argon2id for passwords (per spec); HMAC-SHA256 with the platform key for the
relay signature; constant-time comparisons everywhere secrets are checked.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from urllib.parse import quote


# ---- password hashing (Argon2id) -------------------------------------------
def hash_password(password: str) -> str:
    from argon2 import PasswordHasher
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2).hash(password)


def verify_password(stored: str, password: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError
    try:
        return PasswordHasher().verify(stored, password)
    except (VerifyMismatchError, VerificationError):
        return False


# ---- high entropy tokens and hashes ----------------------------------------
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def redact(value: str | None, keep: int = 4) -> str:
    """Mask a secret for logs: keep first `keep` chars only."""
    if not value:
        return ""
    return value[:keep] + "…(redacted)"


# ---- relay signature --------------------------------------------------------
# Signature binds method, normalized path, target workspace, generation,
# timestamp and nonce. Browser never supplies the target address.
SIG_MAX_AGE_SECONDS = 120


def normalize_path(path: str) -> str:
    path = path.split("?", 1)[0]
    # collapse duplicate slashes, keep percent-encoding case as-is
    path = re.sub(r"/{2,}", "/", path)
    return path or "/"


def _relay_mac(key: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    mac = hmac.new(key.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def sign_relay_request(
    signing_key: str,
    *,
    method: str,
    path: str,
    workspace_id: str,
    generation: int,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> str:
    """Return `<timestamp>.<nonce>.<mac>`; timestamp/nonce travel inside the sig."""
    import time
    ts = timestamp if timestamp is not None else int(time.time())
    n = nonce or secrets.token_hex(16)
    payload = {
        "m": method.upper(), "p": normalize_path(path), "w": str(workspace_id),
        "g": int(generation), "t": ts, "n": n,
    }
    return f"{ts}.{n}.{_relay_mac(signing_key, payload)}"


def verify_relay_signature(
    signing_key: str,
    signature: str,
    *,
    method: str,
    path: str,
    workspace_id: str,
    generation: int,
    now: int | None = None,
) -> bool:
    """Verify the compact signature, enforcing expiry and method/path/workspace binding."""
    import time
    parts = signature.split(".", 2)
    if len(parts) != 3:
        return False
    ts_s, nonce, mac = parts
    try:
        ts = int(ts_s)
    except ValueError:
        return False
    current = now if now is not None else int(time.time())
    if abs(current - ts) > SIG_MAX_AGE_SECONDS:
        return False
    payload = {
        "m": method.upper(), "p": normalize_path(path), "w": str(workspace_id),
        "g": int(generation), "t": ts, "n": nonce,
    }
    expected = _relay_mac(signing_key, payload)
    return hmac.compare_digest(expected, mac)


# ---- cookie helpers ---------------------------------------------------------
def host_cookie(name: str, value: str, *, max_age: int, secure: bool = False, path: str = "/") -> dict:
    parts = [
        f"{name}={quote(value)}",
        f"Max-Age={max_age}",
        f"Path={path}",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if secure:
        parts.append("Secure")
    # no Domain -> host-only
    return {"set_cookie": "; ".join(parts), "name": name, "value": value}
