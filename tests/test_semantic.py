from datetime import date

import pytest

from astra.db import execute, fetch_all
from astra.memory.semantic import compute_sponsor_profiles
from astra.models import ParsedStudy
from astra.queries.trials import upsert_studies

PAST = date(2020, 1, 1)


def make_study(nct_id: str, sponsor: str, **overrides) -> ParsedStudy:
    fields = {
        "nct_id": nct_id,
        "condition_group": "oncology",
        "title": f"Trial {nct_id}",
        "overall_status": "COMPLETED",
        "sponsor": sponsor,
        "sponsor_class": "INDUSTRY",
        "is_applicable_trial": True,
        "primary_completion_date": PAST,
        "primary_completion_type": "ACTUAL",
    }
    return ParsedStudy(**(fields | overrides))


async def profiles() -> dict[str, dict]:
    rows = await fetch_all("SELECT * FROM sponsor_profiles")
    return {row["sponsor"]: row for row in rows}


@pytest.fixture
async def seeded(db):
    await upsert_studies(
        [
            # Acme: 4 applicable completed trials with results due, 2 of them posted.
            make_study("NCT00000001", "Acme", has_results=True,
                       results_first_posted=date(2021, 1, 1)),  # 366 days after completion
            make_study("NCT00000002", "Acme", has_results=True,
                       results_first_posted=date(2020, 7, 1)),  # 182 days
            make_study("NCT00000003", "Acme"),
            make_study("NCT00000004", "Acme"),
            # Not applicable: counts towards total_studies only.
            make_study("NCT00000005", "Acme", is_applicable_trial=False, has_results=True),
            # Applicable but completed less than 12 months ago: results not due yet.
            make_study("NCT00000006", "Acme", primary_completion_date=date.today()),
            # Small Co: only 2 applicable completed trials -> no compliance rate.
            make_study("NCT00000007", "Small Co", has_results=True),
            make_study("NCT00000008", "Small Co"),
        ]
    )  # fmt: skip
    return db


async def test_profile_counts_and_rates(seeded):
    await compute_sponsor_profiles()
    acme = (await profiles())["Acme"]
    assert acme["total_studies"] == 6
    assert acme["applicable_completed"] == 4
    assert acme["results_posted"] == 2
    assert acme["missing_results"] == 2
    assert acme["compliance_rate"] == pytest.approx(0.5)
    assert acme["avg_reporting_delay_days"] == pytest.approx(274)


async def test_rate_is_null_below_three_applicable_trials(seeded):
    await compute_sponsor_profiles()
    small = (await profiles())["Small Co"]
    assert small["applicable_completed"] == 2
    assert small["missing_results"] == 1
    assert small["compliance_rate"] is None


async def test_recompute_is_idempotent_and_can_reach_one(seeded):
    await execute("UPDATE studies SET has_results = TRUE WHERE sponsor = 'Acme'")
    await compute_sponsor_profiles()
    first = await profiles()
    await compute_sponsor_profiles()
    second = await profiles()
    assert len(second) == 2
    assert first["Acme"]["compliance_rate"] == pytest.approx(1.0)
    assert {k: v for k, v in first["Acme"].items() if k != "updated_at"} == {
        k: v for k, v in second["Acme"].items() if k != "updated_at"
    }
