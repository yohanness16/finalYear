import asyncio
from logging.config import fileConfig
import os
import sys
from os.path import abspath, dirname

from dotenv import load_dotenv
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

BASE_DIR = dirname(dirname(abspath(__file__)))
sys.path.insert(0, BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.db.base import Base
from app.models.user import User
from app.models.assignment import Assignment
from app.models.vehicle import Vehicle
from app.models.route import Route
from app.models.trip_history import TripHistory
from app.models.raw_telemetry import RawTelemetry

target_metadata = Base.metadata

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DATABASE_URL = DATABASE_URL.replace("%", "%%")

config.set_main_option("sqlalchemy.url", DATABASE_URL)


def run_migrations_offline():
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())