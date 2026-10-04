"""The full graph with fake models: no LLM, embedding or network calls."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.store.memory import InMemoryStore

from astra import llm
from astra.agents.react_agent import react_agent_for
from astra.agents.registry import AGENTS
from astra.config import settings
from astra.db import fetch_all
from astra.graph.builder import build_graph
from astra.memory.procedural import seed_default_rules
from astra.memory.semantic import compute_sponsor_profiles
from astra.models import AgentFindings, EvidenceItem, ParsedStudy, RoutingDecision, SignalDraft
from astra.queries import runs as run_queries
from astra.queries.trials import upsert_studies
from astra.runner import TOKEN_EVENTS, replay_run, stream_run

USAGE = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
CONFIDENCE = {"missing_results": 0.9, "timeline": 0.5}  # threshold 0.65 and 0.6


def ai(text: str = "", tool_calls: list | None = None) -> AIMessage:
    return AIMessage(text, tool_calls=tool_calls or [], usage_metadata=USAGE)


def agent_of(messages) -> str:
    """Which specialist is calling, read from the header of its system prompt."""
    header = messages[0].content.splitlines()[0].removeprefix("# ")
    return next(name for name, config in AGENTS.items() if config.display_name == header)


class FakeModels:
    def __init__(self, route: RoutingDecision, failing_agent: str | None = None):
        self.route = route
        self.failing_agent = failing_agent
        self.route_calls = 0

    def tool_model(self, role, tools):
        def reply(messages):
            if agent_of(messages) == self.failing_agent:
                raise RuntimeError("provider error")
            if any(isinstance(message, ToolMessage) for message in messages):
                return ai("done")
            return ai(tool_calls=[{"name": tools[0].name, "args": {}, "id": "call-1"}])

        return RunnableLambda(reply)

    def structured_model(self, role, schema):
        def reply(messages):
            if schema is RoutingDecision:
                self.route_calls += 1
                parsed = self.route
            else:
                agent = agent_of(messages)
                evidence = [EvidenceItem(source="registry", reference="NCT00000001", detail="d")]
                signal = SignalDraft(
                    nct_id="NCT00000001",
                    title=f"{agent} finding",
                    summary="s",
                    evidence=evidence,
                    confidence=CONFIDENCE[agent],
                )
                parsed = AgentFindings(signals=[signal], notes=f"{agent} notes")
            return {"raw": ai("{}"), "parsed": parsed, "parsing_error": None}

        return RunnableLambda(reply)

    def plain_model(self, role, temperature=0.0):
        return RunnableLambda(lambda messages: ai("## Summary\nTwo findings."))


@pytest.fixture
async def seeded(db):
    await upsert_studies(
        [ParsedStudy(nct_id="NCT00000001", condition_group="oncology", title="t",
                     overall_status="COMPLETED", sponsor="Acme")]
    )  # fmt: skip
    await compute_sponsor_profiles()
    await seed_default_rules()
    return db


def use_fakes(monkeypatch, fakes: FakeModels) -> None:
    for name in ("tool_model", "structured_model", "plain_model"):
        monkeypatch.setattr(llm, name, getattr(fakes, name))
    react_agent_for.cache_clear()  # subgraphs must be rebuilt with the fake models


@pytest.fixture(autouse=True)
def rebuild_subgraphs_afterwards():
    yield
    react_agent_for.cache_clear()


async def run(task: str, store=None) -> tuple[str, list[dict]]:
    graph = build_graph(store or InMemoryStore())
    run_id = str(await run_queries.create_run(task))
    return run_id, [event async for event in stream_run(graph, run_id)]


def route_to(*agents: str) -> RoutingDecision:
    return RoutingDecision(in_scope=True, agents=list(agents), condition_group=None, reason="r")


async def test_full_run(seeded, monkeypatch):
    use_fakes(monkeypatch, FakeModels(route_to("missing_results", "timeline")))
    store = InMemoryStore()
    run_id, events = await run("Find overdue and delayed oncology trials", store)
    types = [event["type"] for event in events]

    assert types[:2] == ["run_started", "routing"]
    assert types[-4:] == ["validation", "review_gate", "brief", "run_finished"]
    started = {event["agent"] for event in events if event["type"] == "agent_started"}
    assert started == {"missing_results", "timeline"}  # only the routed specialists ran
    tool_agents = {event["agent"] for event in events if event["type"] == "tool_called"}
    assert tool_agents == {"missing_results", "timeline"}
    # Fan-in: the validator runs exactly once, after both parallel specialists finished.
    assert types.count("validation") == 1
    last_finished = max(i for i, kind in enumerate(types) if kind == "agent_finished")
    assert last_finished < types.index("validation")

    signals = await fetch_all("SELECT agent, status FROM signals ORDER BY agent")
    assert [(row["agent"], row["status"]) for row in signals] == [
        ("missing_results", "auto_approved"),
        ("timeline", "pending_review"),
    ]

    row = await run_queries.get_run(run_id)
    token_events = [event for event in events if event["type"] in TOKEN_EVENTS]
    assert row["status"] == "completed"
    assert row["input_tokens"] == sum(event["input_tokens"] for event in token_events) > 0
    assert row["output_tokens"] == sum(event["output_tokens"] for event in token_events)
    assert (row["signals_count"], row["pending_review_count"]) == (2, 1)
    assert set(row["agent_stats"]) == {"missing_results", "timeline"}
    assert row["brief"].startswith("## Summary")
    assert len(row["events"]) == len(events)

    episodes = await store.asearch(("episodes", "timeline"))
    assert "timeline_delay" in episodes[0].value["summary"]


async def test_a_failing_agent_does_not_fail_the_run(seeded, monkeypatch):
    fakes = FakeModels(route_to("missing_results", "side_effect"), failing_agent="side_effect")
    use_fakes(monkeypatch, fakes)
    run_id, events = await run("Check oncology trials")

    finished = {e["agent"]: e for e in events if e["type"] == "agent_finished"}
    assert "provider error" in finished["side_effect"]["error"]
    assert finished["missing_results"]["error"] is None
    assert (await run_queries.get_run(run_id))["status"] == "completed"
    assert len(await fetch_all("SELECT * FROM signals")) == 1


async def test_blocked_input_goes_straight_to_finalize(seeded, monkeypatch):
    fakes = FakeModels(route_to("missing_results"))
    use_fakes(monkeypatch, fakes)
    run_id, events = await run("ab")

    assert [event["type"] for event in events] == ["run_started", "input_blocked", "run_finished"]
    assert fakes.route_calls == 0
    assert (await run_queries.get_run(run_id))["status"] == "blocked"
    guardrail = await fetch_all("SELECT stage, action FROM guardrail_events")
    assert [(row["stage"], row["action"]) for row in guardrail] == [("input", "blocked")]


async def test_out_of_scope_task_is_blocked_by_the_supervisor(seeded, monkeypatch):
    off_topic = RoutingDecision(in_scope=False, agents=[], condition_group=None, reason="recipe")
    use_fakes(monkeypatch, FakeModels(off_topic))
    run_id, events = await run("What is a good banana bread recipe?")

    assert [event["type"] for event in events] == ["run_started", "input_blocked", "run_finished"]
    assert (await run_queries.get_run(run_id))["status"] == "blocked"


async def test_replay_yields_the_stored_events(seeded, monkeypatch):
    use_fakes(monkeypatch, FakeModels(route_to("timeline")))
    monkeypatch.setattr(settings, "replay_delay_ms", 0)
    run_id, events = await run("Look for silent delays")

    replayed = [event async for event in replay_run(run_id)]
    assert replayed == events
