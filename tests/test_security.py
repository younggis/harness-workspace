"""Offline unit tests for identifiers, hashing, CSRF and relay signatures."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "common")):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness_common.security import (
    constant_time_eq, hash_password, new_token, normalize_path,
    sha256_text, sign_relay_request, token_hash, verify_password,
    verify_relay_signature,
)


def test_password_hash_argon2_and_verify():
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "wrong")


def test_tokens_and_hashes_are_stable_and_distinct():
    a, b = new_token(), new_token()
    assert a != b
    assert token_hash(a) == token_hash(a)
    assert token_hash(a) != a
    assert len(token_hash(a)) == 64
    assert sha256_text("x") == sha256_text("x")


def test_constant_time_eq_rejects_non_strings():
    assert constant_time_eq("abc", "abc")
    assert not constant_time_eq("abc", "abd")
    assert not constant_time_eq(None, "abc")  # type: ignore[arg-type]


def test_normalize_path_collapses_slashes_and_strips_query():
    assert normalize_path("/a//b/c?x=1") == "/a/b/c"
    assert normalize_path("") == "/"


def test_relay_signature_roundtrip_and_binding():
    key = "k"
    sig = sign_relay_request(key, method="GET", path="/_platform/file?x=1",
                             workspace_id="w1", generation=2, timestamp=1000, nonce="n1")
    assert verify_relay_signature(key, sig, method="GET", path="/_platform/file?x=1",
                                  workspace_id="w1", generation=2, now=1000)
    # Binding: wrong method / path / workspace / generation / key all fail.
    assert not verify_relay_signature(key, sig, method="POST", path="/_platform/file?x=1",
                                      workspace_id="w1", generation=2, now=1000)
    assert not verify_relay_signature(key, sig, method="GET", path="/_platform/other",
                                      workspace_id="w1", generation=2, now=1000)
    assert not verify_relay_signature(key, sig, method="GET", path="/_platform/file?x=1",
                                      workspace_id="w2", generation=2, now=1000)
    assert not verify_relay_signature(key, sig, method="GET", path="/_platform/file?x=1",
                                      workspace_id="w1", generation=3, now=1000)
    assert not verify_relay_signature("other", sig, method="GET", path="/_platform/file?x=1",
                                      workspace_id="w1", generation=2, now=1000)


def test_relay_signature_expiry():
    key = "k"
    sig = sign_relay_request(key, method="GET", path="/p", workspace_id="w", generation=1,
                             timestamp=1000, nonce="n")
    assert not verify_relay_signature(key, sig, method="GET", path="/p",
                                      workspace_id="w", generation=1, now=2000)
