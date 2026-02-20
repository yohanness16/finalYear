from logging.config import fileConfig
import os
import sys
from os.path import abspath, dirname

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from alembic import context

# 1. FIX PYTHON PATH: Ensure the project root is in sys.path so 'app' can be found
# Current file is in project/migrations/env.py, so we need project/
BASE_DIR = dirname(dirname(abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 2. LOAD ENVIRONMENT VARIABLES
load_dotenv(os.path.join(BASE_DIR, ".env"))

# 3. IMPORT THE BASE: Based on your code screenshot, Base is in app/db/base.py
from app.db.base import Base 

# 4. IMPORT ALL MODELS: Autogenerate only works if models are imported here
# These match the filenames in your app/models/ folder
from app.models.user import User
from app.models.assignment import Assignment
from app.models.vehicle import Vehicle
from app.models.route import Route
from app.models.trip_history import TripHistory
from app.models.raw_telemetry import RawTelemetry
# Add any others from your folder here...

# this is the Alembic Config object

load_dotenv(os.path.join(BASE_DIR, ".env"))
config = context.config

# 5. DYNAMICALLY SET DB URL: Override alembic.ini with the one from your .env
database_url = os.getenv("DATABASE_URL")
if database_url:
    # Handle the 'postgres://' vs 'postgresql://' issue if necessary
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the metadata for autogenerate
target_metadata = Base.metadata

def include_object(object, name, type_, reflected, compare_to):
    # This tells Alembic to IGNORE tables it didn't create
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    return True



def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            include_object=include_object,
            # This ensures that your local schema changes are detected
            compare_type=True 
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

