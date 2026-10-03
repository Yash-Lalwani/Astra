import psycopg

from astra.config import settings
from astra.db import apply_schema, fetch_one

EXPECTED_TABLES = {
    "studies", "papers", "study_papers", "sponsor_profiles", "runs",
    "signals", "agent_rules", "guardrail_events", "eval_runs",
}  # fmt: skip


async def test_schema_applies_twice(db_pool):
    await apply_schema()
    await apply_schema()
    async with db_pool.connection() as conn:
        cursor = await conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = {row["tablename"] for row in await cursor.fetchall()}
    assert EXPECTED_TABLES <= tables


async def test_pgvector_extension_installed(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        assert await cursor.fetchone() is not None


async def test_pool_replaces_connections_the_server_dropped(db_pool):
    # Simulates Neon suspending: the server ends every pooled session.
    async with await psycopg.AsyncConnection.connect(
        settings.test_database_url, autocommit=True
    ) as admin:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
    assert await fetch_one("SELECT 1 AS ok") == {"ok": 1}
