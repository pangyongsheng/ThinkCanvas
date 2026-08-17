"""Alembic env.py - async support (v2: 只管 beta schema)。"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import get_settings
from app.db.session_v2 import BaseV2
import app.db.models_v2  # noqa: F401 # 触发 __init__.py 加载所有 v2 模型

config = context.config

config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseV2.metadata

def _include_object(object, name, type_, reflected, compare_to):
    """autogenerate 时跳过 alembic 自己的版本表。"""
    if type_ == "table" and name == "alembic_version":
        return False
    return True

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="beta",  # 加这一行
        include_object=_include_object,  # 加这一行
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"server_settings": {"search_path": "beta"}},  # 改成这个
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


run_migrations_online()