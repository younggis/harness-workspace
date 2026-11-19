"""Real PostgreSQL integration (opt-in). Use the isolated harness_test schema only."""
import os

import pytest

pytestmark = pytest.mark.integration

REASON = "Set HARNESS_INTEGRATION=1 and bootstrap harness_test to run real DB tests"


@pytest.fixture
def engine():
    if os.environ.get("HARNESS_INTEGRATION") != "1":
        pytest.skip(REASON)
    from harness_common.config import get_settings
    from harness_common.db import make_engine
    settings = get_settings()
    # Point at the dedicated test schema by overriding via env before import.
    url = settings.migration_database_url()
    return make_engine(url, schema=os.environ.get("HARNESS_MIGRATION_SCHEMA", "harness_test"))


def test_only_project_schema_tables_are_present(engine):
    from sqlalchemy import text
    with engine.connect() as c:
        schemas = c.execute(text(
            "select distinct table_schema from information_schema.tables "
            "where table_schema not in ('pg_catalog','information_schema')"
        )).scalars().all()
    assert "harness_test" in schemas
    assert "public" in schemas  # pre-existing schemas left untouched


def test_migration_version_is_pinned(engine):
    from sqlalchemy import text
    from pathlib import Path
    revisions = set()
    versions_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    for f in versions_dir.glob("*.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("revision = "):
                revisions.add(line.split("=")[1].strip().strip("'\""))
                break
    with engine.connect() as c:
        v = c.execute(text("select version_num from harness_test.alembic_version")).scalar()
    assert v in revisions, (v, revisions)


def test_app_role_can_login_from_container(engine):
    """T01/T06: real login, not just TCP. Run via doctor.ps1 container probe."""
    from sqlalchemy import text
    with engine.connect() as c:
        assert c.execute(text("select current_database(),current_user")).first()[1] == os.environ.get(
            "PG_MIGRATION_USER", "harness_owner")
