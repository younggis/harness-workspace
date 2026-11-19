"""Interactive admin bootstrap CLI (no built-in default password).

Run via: python -m app.cli admin-create
It creates the FIRST platform administrator with an interactively entered password,
or refuses if one already exists.
"""
from __future__ import annotations

import os
import sys
import uuid
from getpass import getpass

from sqlalchemy import select

from harness_common import models as m
from harness_common.config import get_settings
from harness_common.db import make_engine, make_session_factory
from harness_common.security import hash_password


def admin_create() -> int:
    settings = get_settings()
    engine = make_engine(settings.app_database_url(), schema=settings.pg_schema)
    factory = make_session_factory(engine)
    with factory() as db:
        existing = db.execute(select(m.User).where(m.User.is_platform_admin.is_(True))).scalar_one_or_none()
        if existing:
            print(f"A platform administrator already exists: {existing.login_norm}")
            return 1
        # Interactive by default. For scripted bootstrap, set HARNESS_ADMIN_LOGIN
        # and HARNESS_ADMIN_PASSWORD in the environment (still no built-in default).
        scripted = os.environ.get("HARNESS_ADMIN_PASSWORD") is not None
        if scripted:
            login = os.environ.get("HARNESS_ADMIN_LOGIN", "admin").strip().lower()
            display = os.environ.get("HARNESS_ADMIN_NAME", "Platform Administrator").strip()
            pw = os.environ["HARNESS_ADMIN_PASSWORD"]
        else:
            login = input("Admin login: ").strip().lower()
            display = input("Display name: ").strip() or "Platform Administrator"
            pw = getpass("Password (min 12 chars): ")
            if pw != getpass("Confirm password: "):
                print("Passwords do not match")
                return 2
        if not login:
            print("Login must not be empty")
            return 2
        if len(pw) < 12:
            print("Password too short")
            return 2
        user = m.User(id=uuid.uuid4(), login_norm=login, display_name=display,
                      password_hash=hash_password(pw), is_platform_admin=True)
        db.add(user)
        db.add(m.AuditEvent(actor_id=user.id, action="admin.create", target=login, result="success"))
        db.commit()
        print(f"Created platform administrator: {login}")
        return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "admin-create":
        print("Usage: python -m app.cli admin-create")
        return 2
    return admin_create()


if __name__ == "__main__":
    raise SystemExit(main())
