import pytest

from astra.db import fetch_all, fetch_one
from astra.guardrails.validator import validate_signals
from astra.memory.semantic import compute_sponsor_profiles
from astra.models import AgentResult, EvidenceItem, ParsedStudy, SignalDraft
from astra.queries.trials import upsert_studies

EVIDENCE = [EvidenceItem(source="registry", reference="NCT00000001", detail="93 months overdue")]


def draft(**overrides) -> SignalDraft:
    fields = {
        "nct_id": "NCT00000001",
        "title": "Results overdue",
        "summary": "s",
        "evidence": EVIDENCE,
        "confidence": 0.8,
    }
    return SignalDraft(**(fields | overrides))


def result(agent: str, *signals: SignalDraft) -> AgentResult:
    return AgentResult(agent=agent, signals=list(signals))


@pytest.fixture
async def seeded(db):
    await upsert_studies(
        [
            ParsedStudy(nct_id=f"NCT0000000{n}", condition_group="oncology", title="t",
                        overall_status="COMPLETED", sponsor="Acme Pharma")
            for n in (1, 2)
        ]
    )  # fmt: skip
    await compute_sponsor_profiles()
    return db


async def test_valid_signal_gets_agent_fields_from_the_registry(seeded):
    kept, dropped = await validate_signals([result("missing_results", draft())], None)
    assert dropped == []
    assert (kept[0].agent, kept[0].signal_type, kept[0].threshold) == (
        "missing_results",
        "missing_results",
        0.65,
    )
    assert kept[0].citation_verified is None


@pytest.mark.parametrize(
    ("agent", "signal", "reason"),
    [
        ("missing_results", draft(nct_id=None, sponsor="Acme Pharma"), "without an nct_id"),
        ("track_record", draft(nct_id=None), "neither a trial nor a sponsor"),
        ("missing_results", draft(nct_id="NCT09999999"), "unknown nct_id"),
        ("track_record", draft(nct_id=None, sponsor="Imaginary Inc"), "unknown sponsor"),
        ("missing_results", draft(evidence=[]), "no evidence"),
    ],
)
async def test_bad_signals_are_dropped(seeded, agent, signal, reason):
    kept, dropped = await validate_signals([result(agent, signal)], None)
    assert kept == []
    assert reason in dropped[0]["reason"]


async def test_ids_and_sponsor_names_are_normalised(seeded):
    signal = draft(nct_id=" nct00000001 ", sponsor="acme pharma", related_nct_ids=["NCT09999999"])
    kept, _ = await validate_signals([result("missing_results", signal)], None)
    assert kept[0].nct_id == "NCT00000001"
    assert kept[0].sponsor == "Acme Pharma"
    assert kept[0].related_nct_ids == []  # unknown related trials are removed


async def test_confidence_is_clamped(seeded):
    kept, _ = await validate_signals([result("missing_results", draft(confidence=1.7))], None)
    assert kept[0].confidence == 1.0


async def test_duplicates_keep_the_highest_confidence(seeded):
    signals = [draft(confidence=0.6), draft(confidence=0.9), draft(nct_id="NCT00000002")]
    kept, dropped = await validate_signals([result("side_effect", *signals)], None)
    assert sorted((signal.nct_id, signal.confidence) for signal in kept) == [
        ("NCT00000001", 0.9), ("NCT00000002", 0.8)
    ]  # fmt: skip
    assert [entry["reason"] for entry in dropped] == ["duplicate of a stronger signal"]


async def test_same_trial_from_two_agents_is_kept_twice(seeded):
    kept, _ = await validate_signals(
        [result("missing_results", draft()), result("timeline", draft())], None
    )
    assert len(kept) == 2


async def test_drops_are_logged_only_for_a_run(seeded):
    await validate_signals([result("missing_results", draft(nct_id="NCT09999999"))], None)
    assert await fetch_all("SELECT * FROM guardrail_events") == []

    run = await fetch_one("INSERT INTO runs (task) VALUES ('t') RETURNING run_id")
    await validate_signals(
        [result("missing_results", draft(nct_id="NCT09999999"))], str(run["run_id"])
    )
    events = await fetch_all("SELECT stage, action, agent, detail FROM guardrail_events")
    assert [(e["stage"], e["action"], e["agent"]) for e in events] == [
        ("signal_validation", "dropped", "missing_results")
    ]
    assert events[0]["detail"]["nct_id"] == "NCT09999999"
