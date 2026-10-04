import logging
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from astra.config import REPO_ROOT, settings

logger = logging.getLogger(__name__)

SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"

_pool: AsyncConnectionPool | None = None


async def get_pool() -> AsyncConnectionPool:
    """Return the one shared pool, opening it on first use."""
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        # autocommit + dict_row are what LangGraph's AsyncPostgresStore expects from a shared
        # pool; prepare_threshold=None keeps it safe on Neon's pooled endpoint as well.
        _pool = AsyncConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=10,
            open=False,
            # Neon suspends idle compute and drops its connections; test each one before use.
            check=AsyncConnectionPool.check_connection,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
        )
    await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def execute(sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(sql, params)


async def execute_many(sql: str, params_seq: Sequence[Sequence[Any] | Mapping[str, Any]]) -> None:
    if not params_seq:
        return
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.executemany(sql, params_seq)


async def fetch_all(
    sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(sql, params)
        return await cursor.fetchall()


async def fetch_one(
    sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(sql, params)
        return await cursor.fetchone()


async def database_ok() -> bool:
    try:
        await fetch_one("SELECT 1")
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False
    return True


async def apply_schema() -> None:
    """Apply sql/schema.sql. Every statement is idempotent, so this is safe on every startup."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_PATH.read_text())
    logger.info("Schema applied")
