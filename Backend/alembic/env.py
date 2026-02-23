"""
Alembic environment — wired to the app's SQLAlchemy Base and settings.

Key decisions:
- DATABASE_URL_SYNC is read from app.core.config (psycopg2 sync driver).
- target_metadata points at Base.metadata so autogenerate works once models
  are imported.
- All app models must be imported here (via app.models) before autogenerate
  can detect them.
"""

import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Make sure `app` package is importable when running alembic from
#    the Backend/ directory (i.e. `alembic upgrade head`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── App imports ───────────────────────────────────────────────────
from app.core.config import settings          # noqa: E402
from app.core.database import Base            # noqa: E402

# Import all model modules so their tables are registered on Base.metadata
# before autogenerate runs.  Add each new model file to app/models/__init__.py.
import app.models  # noqa: E402, F401

# ── Alembic config object ─────────────────────────────────────────
config = context.config

# Override sqlalchemy.url from our typed settings (sync psycopg2 URL).
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

# Python logging via alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support
target_metadata = Base.metadata


# ── Offline mode ──────────────────────────────────────────────────
def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────
def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
