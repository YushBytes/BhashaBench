"""Alembic migration environment.

The database URL is taken from application settings rather than `alembic.ini`,
so a password never has to be written into a committed file and migrations
automatically target whatever the application itself would connect to.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# `alembic` runs this file directly, so `app` is not importable yet. The
# backend directory is this file's grandparent: backend/alembic/env.py.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402  (needs sys.path above)

# Importing the package imports every model, which is what populates
# `Base.metadata`. Autogenerate can only see tables whose classes have been
# imported, so a model missing from `app/models/__init__.py` would silently
# vanish from migrations.
from app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Return the database URL from application settings."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it.

    Used to review the statements a migration would execute, or to hand them
    to a DBA who applies schema changes separately.
    """
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Without these, autogenerate misses column type changes and
            # server-default changes, producing migrations that look complete
            # but leave the schema drifted.
            compare_type=True,
            compare_server_default=True,
            # Render the naming convention into generated migrations so
            # constraint names match what the models declare, and a downgrade
            # can therefore drop them by name.
            render_as_batch=False,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
