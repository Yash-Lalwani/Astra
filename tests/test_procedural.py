import uuid

import pytest
from langchain_core.runnables import RunnableLambda
from langmem.knowledge.extraction import ExtractedMemory

from astra.db import fetch_all, fetch_one
from astra.memory import procedural
from astra.memory.procedural import DEFAULT_RULES, AgentRule, get_rules, learn_from_rejection
from astra.models import EvidenceItem, SavedSignal

NEW_RULE = "Lower confidence when the estimated date falls inside a known disruption window."


@pytest.fixture
async def rejected_signal(db) -> SavedSignal:
    await procedural.seed_default_rules()
    run = await fetch_one("INSERT INTO runs (task) VALUES ('t') RETURNING run_id")
    signal = SavedSignal(
        signal_id=uuid.uuid4(),
        agent="timeline",
        signal_type="timeline_delay",
        threshold=0.6,
        nct_id=None,
        sponsor="Acme",
        title="Trial silently delayed",
        summary="Still recruiting long after its estimated date.",
        evidence=[EvidenceItem(source="registry", reference="NCT00000001", detail="1493 days")],
        confidence=0.95,
        status="auto_approved",
    )
    await fetch_one(
        """
        INSERT INTO signals (signal_id, run_id, agent, signal_type, sponsor, title, summary,
                             evidence, confidence, threshold, status)
        VALUES (%s, %s, 'timeline', 'timeline_delay', 'Acme', 't', 's', '[]', 0.95, 0.6,
                'rejected')
        RETURNING signal_id
        """,
        (signal.signal_id, run["run_id"]),
    )
    return signal


def fake_manager(new_rules: list[str]):
    """Stands in for LangMem: returns the existing rules plus the given new ones."""

    def manage(payload: dict) -> list[ExtractedMemory]:
        kept = [
            ExtractedMemory(id=memory_id, content=rule) for memory_id, rule in payload["existing"]
        ]
        added = [ExtractedMemory(id=str(uuid.uuid4()), content=AgentRule(content=text))
                 for text in new_rules]  # fmt: skip
        return kept + added

    return lambda *args, **kwargs: RunnableLambda(manage)


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    monkeypatch.setattr(procedural.llm, "plain_model", lambda role: None)


async def test_seeding_is_idempotent(db):
    await procedural.seed_default_rules()
    await procedural.seed_default_rules()
    rows = await fetch_all("SELECT agent, source FROM agent_rules")
    assert len(rows) == sum(len(rules) for rules in DEFAULT_RULES.values())
    assert {row["source"] for row in rows} == {"default"}


async def test_get_rules_returns_defaults_in_order(db):
    await procedural.seed_default_rules()
    rules = await get_rules("timeline")
    assert [rule["rule_text"] for rule in rules] == DEFAULT_RULES["timeline"]


async def test_rejection_adds_a_learned_rule_linked_to_the_signal(rejected_signal, monkeypatch):
    monkeypatch.setattr(procedural, "create_memory_manager", fake_manager([NEW_RULE]))

    change = await learn_from_rejection(rejected_signal, "The COVID window explains the delay.")

    assert change.action == "added"
    assert change.rule_text == NEW_RULE
    rules = await get_rules("timeline")
    learned = rules[-1]
    assert learned["source"] == "learned"
    assert learned["learned_from_signal_id"] == rejected_signal.signal_id
    assert learned["reviewer_reason"] == "The COVID window explains the delay."


async def test_no_rule_when_existing_rules_cover_it(rejected_signal, monkeypatch):
    monkeypatch.setattr(procedural, "create_memory_manager", fake_manager([]))
    change = await learn_from_rejection(rejected_signal, "Already covered by a rule.")
    assert change.action == "none"
    assert len(await get_rules("timeline")) == len(DEFAULT_RULES["timeline"])


async def test_an_exact_duplicate_is_not_inserted(rejected_signal, monkeypatch):
    duplicate = DEFAULT_RULES["timeline"][0]
    monkeypatch.setattr(procedural, "create_memory_manager", fake_manager([duplicate]))
    change = await learn_from_rejection(rejected_signal, "Duplicate of a default rule.")
    assert change.action == "none"
    assert len(await get_rules("timeline")) == len(DEFAULT_RULES["timeline"])
