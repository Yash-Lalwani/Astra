import os

# Must be set before astra.config is imported: tests never send LangSmith traces.
os.environ["LANGSMITH_TRACING"] = "false"

import pytest  # noqa: E402

from astra.agents.react_agent import react_agent_for  # noqa: E402
from astra.config import settings  # noqa: E402
from astra.db import apply_schema, close_pool, get_pool  # noqa: E402
from astra.memory.procedural import seed_default_rules  # noqa: E402
from astra.memory.semantic import compute_sponsor_profiles  # noqa: E402
from astra.models import ParsedStudy  # noqa: E402
from astra.queries.trials import upsert_studies  # noqa: E402

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


@pytest.fixture
async def seeded(db):
    """One trial, its sponsor profile and the default rules."""
    await upsert_studies(
        [ParsedStudy(nct_id="NCT00000001", condition_group="oncology", title="t",
                     overall_status="COMPLETED", sponsor="Acme")]
    )  # fmt: skip
    await compute_sponsor_profiles()
    await seed_default_rules()
    return db


@pytest.fixture(autouse=True)
def rebuild_subgraphs_afterwards():
    yield
    react_agent_for.cache_clear()


ADMIN_KEY = "test-admin-key"


@pytest.fixture
async def api(seeded, monkeypatch):
    """An HTTP client for the app, with fake models and an in-memory episode store.
    Calls go straight to the app (no server), and the app's startup work is done here."""
    import httpx
    from fakes import FakeModels, route_to, use_fakes
    from langgraph.store.memory import InMemoryStore

    from astra.api.main import app
    from astra.graph.builder import build_graph

    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY)
    monkeypatch.setattr(settings, "replay_delay_ms", 0)
    use_fakes(monkeypatch, FakeModels(route_to("missing_results", "timeline")))
    app.state.store = InMemoryStore()
    app.state.graph = build_graph(app.state.store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        yield client
