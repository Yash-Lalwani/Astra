import os

# Must be set before astra.config is imported: tests never send LangSmith traces.
os.environ["LANGSMITH_TRACING"] = "false"

import pytest  # noqa: E402

from astra.config import settings  # noqa: E402
from astra.db import apply_schema, close_pool, get_pool  # noqa: E402

settings.database_url = settings.test_database_url


@pytest.fixture(scope="session")
async def db_pool():
    await apply_schema()
    yield await get_pool()
    await close_pool()


@pytest.fixture
async def db(db_pool):
    """The test database with every table emptied."""
    async with db_pool.connection() as conn:
        await conn.execute(
            "TRUNCATE studies, papers, study_papers, sponsor_profiles, runs, signals,"
            " agent_rules, guardrail_events, eval_runs CASCADE"
        )
    return db_pool
