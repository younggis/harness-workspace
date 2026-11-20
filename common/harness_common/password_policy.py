"""Local password strength policy (no external breach-corpus dependency)."""
from __future__ import annotations

import re

MIN_LENGTH = 12

_WEAK = {
    "password", "password123", "password1234", "123456789012", "qwerty123456", "admin12345",
    "letmein12345", "welcome12345", "changeme1234", "harness12345",
}


def validate_password(password: str, *, login: str = "") -> str | None:
    """Return an error message when weak, otherwise None."""
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters"
    if len(password) > 512:
        return "Password is too long"
    if password.lower() in _WEAK:
        return "Password is too common"
    classes = sum(bool(re.search(p, password)) for p in (
        r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]",
    ))
    if classes < 3:
        return "Password must use at least 3 of: lowercase, uppercase, digit, symbol"
    if login and login.lower() in password.lower():
        return "Password must not contain the account name"
    return None
