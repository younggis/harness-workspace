"""Alembic environment. Scoped to the dedicated harness schema only."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "common")):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness_common.config import get_settings  # noqa: E402
from harness_common.models import Base  # noqa: E402

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

settings = get_settings()
schema = os.environ.get("HARNESS_MIGRATION_SCHEMA", settings.pg_schema)
config.set_main_option("sqlalchemy.url", settings.migration_database_url())


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Never touch objects outside our schema.
    if hasattr(obj, "schema") and obj.schema and obj.schema != schema:
        return False
    return True


def run_migrations(connection):  # type: ignore[no-untyped-def]
    connection.exec_driver_sql(f'SET search_path TO "{schema}", pg_catalog')
    # End the implicit transaction opened by SET, otherwise Alembic begins a
    # savepoint and the outer transaction rolls back on connection close.
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=schema,
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = engine_from_config(config.get_section(config.config_ini_section),
                                prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_migrations(connection)


run_migrations_online()
