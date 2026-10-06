import json
import uuid

import pytest
from conftest import ADMIN_KEY
from langchain_core.runnables import RunnableLambda
from langmem.knowledge.extraction import ExtractedMemory

from astra.memory import procedural
from astra.memory.procedural import AgentRule
from astra.queries import runs as run_queries

ADMIN = {"X-Admin-Key": ADMIN_KEY}


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = [
            line[len("data:") :].strip() for line in block.splitlines() if line.startswith("data:")
        ]
        if data:
            events.append(json.loads("".join(data)))
    return events


async def finished_run(api) -> str:
    created = await api.post("/runs", json={"task": "Find overdue and delayed oncology trials"})
    run_id = created.json()["run_id"]
    await api.get(f"/runs/{run_id}/stream")
    return run_id


async def test_create_stream_and_replay_a_run(api):
    created = await api.post("/runs", json={"task": "Find overdue oncology trials"})
    assert created.status_code == 201
    run_id = uuid.UUID(created.json()["run_id"])
    assert created.json()["status"] == "queued"

    live = await api.get(f"/runs/{run_id}/stream")
    assert live.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(live.text)
    assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished"
    assert "tool_called" in {event["type"] for event in events}

    detail = (await api.get(f"/runs/{run_id}")).json()
    assert detail["status"] == "completed"
    assert {signal["agent"] for signal in detail["signals"]} == {"missing_results", "timeline"}
    assert all(uuid.UUID(signal["signal_id"]) for signal in detail["signals"])
    assert set(detail["agent_stats"]) == {"missing_results", "timeline"}

    replay = parse_sse((await api.get(f"/runs/{run_id}/stream")).text)
    assert [event["type"] for event in replay] == [event["type"] for event in events]


async def test_stream_of_a_running_run_is_409(api):
    run_id = await run_queries.create_run("Find overdue oncology trials")
    await run_queries.claim_run(run_id)
    response = await api.get(f"/runs/{run_id}/stream")
    assert response.status_code == 409


async def test_unknown_ids_are_404(api):
    assert (await api.get(f"/runs/{uuid.uuid4()}")).status_code == 404
    assert (await api.get(f"/signals/{uuid.uuid4()}")).status_code == 404
    assert (await api.get("/trials/NCT09999999")).status_code == 404
    assert (await api.get("/sponsors/profile", params={"name": "Nobody"})).status_code == 404


async def test_brief_download(api):
    run_id = await finished_run(api)
    response = await api.get(f"/runs/{run_id}/brief.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert "## Signals" in response.text and "| timeline | NCT00000001 |" in response.text


def fake_rule_learning(monkeypatch, rule: str) -> None:
    def manage(payload):
        return [ExtractedMemory(id=str(uuid.uuid4()), content=AgentRule(content=rule))]

    monkeypatch.setattr(procedural, "create_memory_manager", lambda *a, **k: RunnableLambda(manage))
    monkeypatch.setattr(procedural.llm, "plain_model", lambda role: None)


async def test_review_flow(api, monkeypatch):
    fake_rule_learning(monkeypatch, "Lower confidence for delays inside the COVID window.")
    await finished_run(api)
    queue = (await api.get("/review/queue")).json()
    assert queue["total"] == 1
    pending = queue["items"][0]

    too_short = await api.post(
        f"/review/{pending['signal_id']}",
        json={"decision": "reject", "reason": "no"},
        headers=ADMIN,
    )
    assert too_short.status_code == 422

    rejected = await api.post(
        f"/review/{pending['signal_id']}",
        json={"decision": "reject", "reason": "The delay falls inside the COVID window."},
        headers=ADMIN,
    )
    assert rejected.status_code == 200
    body = rejected.json()
    assert body["signal"]["status"] == "rejected"
    assert body["rule_change"]["action"] == "added"
    rules = (await api.get("/memory/rules", params={"agent": "timeline"})).json()["items"]
    assert rules[-1]["source"] == "learned"
    assert rules[-1]["learned_from_signal_id"] == pending["signal_id"]

    again = await api.post(
        f"/review/{pending['signal_id']}", json={"decision": "approve"}, headers=ADMIN
    )
    assert again.status_code == 409

    approved = (await api.get("/signals", params={"status": "auto_approved"})).json()["items"][0]
    edited = await api.post(
        f"/review/{approved['signal_id']}",
        json={"decision": "edit", "edited_summary": "Clearer summary."},
        headers=ADMIN,
    )
    signal = edited.json()["signal"]
    assert (signal["status"], signal["edited"], signal["summary"]) == (
        "approved", True, "Clearer summary."
    )  # fmt: skip
    assert signal["original_summary"] == approved["summary"]
    assert edited.json()["rule_change"] is None

    rate = (await api.get("/metrics/approval-rate")).json()
    assert rate["overall"][0]["approved"] == 1 and rate["overall"][0]["rejected"] == 1


@pytest.mark.parametrize(
    "path",
    [
        "/runs",
        "/signals?agent=timeline",
        "/review/queue",
        "/sponsors?min_studies=1",
        "/memory/rules?agent=timeline",
        "/memory/episodes?agent=timeline",
        "/evals",
        "/guardrails/events",
        "/agents",
    ],
)
async def test_list_endpoints_return_pages(api, path):
    await finished_run(api)
    response = await api.get(path)
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"items", "total"}
    assert body["total"] == len(body["items"]) or body["total"] > len(body["items"])


async def test_detail_and_system_endpoints(api):
    run_id = await finished_run(api)
    trial = (await api.get("/trials/nct00000001")).json()
    assert trial["study"]["nct_id"] == "NCT00000001"
    assert set(trial["facts"]) >= {"results_due", "timeline", "outcome_comparison"}
    assert len(trial["signals"]) == 2

    sponsor = (await api.get("/sponsors/profile", params={"name": "acme"})).json()
    assert sponsor["profile"]["sponsor"] == "Acme"
    assert len(sponsor["signals"]) == 2

    episodes = (await api.get("/memory/episodes", params={"agent": "timeline"})).json()
    assert episodes["items"][0]["run_id"] == run_id

    stats = (await api.get("/stats")).json()
    assert (stats["trials"], stats["signals_total"], stats["runs_completed"]) == (1, 2, 1)
    assert (await api.get("/health")).json() == {
        "status": "ok", "database": "ok", "layer": "disabled"
    }  # fmt: skip
    assert "supervisor" in (await api.get("/graph")).json()["mermaid"]
    agents = (await api.get("/agents")).json()["items"]
    assert {agent["name"] for agent in agents} == {
        "missing_results", "broken_promises", "track_record", "pattern_finder", "side_effect",
        "timeline",
    }  # fmt: skip


async def test_health_reports_layer_status(api, monkeypatch):
    from fakes import FakeLayer, enable_layer

    assert (await api.get("/health")).json()["layer"] == "disabled"
    enable_layer(monkeypatch, FakeLayer())
    assert (await api.get("/health")).json()["layer"] == "ok"

    async def down(*args, **kwargs):
        raise RuntimeError("unreachable")

    monkeypatch.setattr("astra.tools.evidence_tools.call_layer", down)
    assert (await api.get("/health")).json()["layer"] == "error"
