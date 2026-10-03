from datetime import date

from astra.ingestion.rules import (
    compare_primary_outcomes,
    is_applicable_trial,
    months_between,
    results_due_status,
    timeline_status,
)
from astra.models import Intervention, ParsedStudy, RegisteredOutcome, ReportedOutcome

TODAY = date(2026, 10, 1)


def make_study(**overrides) -> ParsedStudy:
    fields = {
        "nct_id": "NCT00000001",
        "condition_group": "oncology",
        "title": "T",
        "study_type": "INTERVENTIONAL",
        "phases": ["PHASE3"],
        "overall_status": "COMPLETED",
        "sponsor": "Acme",
        "is_fda_regulated": True,
        "interventions": [Intervention(type="DRUG", name="X")],
        "primary_completion_date": date(2020, 1, 15),
        "primary_completion_type": "ACTUAL",
    }
    return ParsedStudy(**(fields | overrides))


# --- applicability -------------------------------------------------------------------


def test_fda_regulated_phase3_is_applicable():
    assert is_applicable_trial(make_study())


def test_observational_or_phase1_only_is_not_applicable():
    assert not is_applicable_trial(make_study(study_type="OBSERVATIONAL"))
    assert not is_applicable_trial(make_study(phases=["PHASE1"]))
    assert not is_applicable_trial(make_study(phases=["EARLY_PHASE1", "PHASE1"]))
    assert not is_applicable_trial(make_study(phases=[]))
    assert is_applicable_trial(make_study(phases=["PHASE1", "PHASE2"]))


def test_not_fda_regulated_is_not_applicable():
    assert not is_applicable_trial(make_study(is_fda_regulated=False))


# --- results due ---------------------------------------------------------------------


def test_results_due_and_months_overdue():
    study = make_study(is_applicable_trial=True, primary_completion_date=date(2024, 1, 15))
    # Deadline 2025-01-15; on 2026-10-01 that is 20 whole months later.
    assert results_due_status(study, TODAY) == {"results_due": True, "months_overdue": 20}


def test_results_not_due_inside_the_twelve_month_window():
    study = make_study(is_applicable_trial=True, primary_completion_date=date(2025, 10, 1))
    assert results_due_status(study, TODAY) == {"results_due": False, "months_overdue": 0}
    just_past = study.model_copy(update={"primary_completion_date": date(2025, 9, 30)})
    assert results_due_status(just_past, TODAY) == {"results_due": True, "months_overdue": 0}


def test_results_not_due_when_posted_estimated_or_not_applicable():
    base = make_study(is_applicable_trial=True)
    for update in (
        {"has_results": True},
        {"primary_completion_type": "ESTIMATED"},
        {"overall_status": "TERMINATED"},
        {"is_applicable_trial": False},
        {"primary_completion_date": None},
    ):
        assert not results_due_status(base.model_copy(update=update), TODAY)["results_due"]


# --- timeline ------------------------------------------------------------------------


def test_silent_delay_for_active_trial_past_estimated_date():
    study = make_study(
        overall_status="RECRUITING",
        primary_completion_type="ESTIMATED",
        primary_completion_date=date(2025, 1, 15),
        last_update_posted=date(2025, 1, 13),
    )
    assert timeline_status(study, TODAY) == {
        "silent_delay": True,
        "days_past_estimated": 624,
        "months_since_update": 20,
        "unknown_status": False,
    }


def test_no_silent_delay_within_180_days_or_when_completed():
    recent = make_study(
        overall_status="RECRUITING",
        primary_completion_type="ESTIMATED",
        primary_completion_date=date(2026, 6, 1),
    )
    assert timeline_status(recent, TODAY)["silent_delay"] is False
    assert timeline_status(recent, TODAY)["days_past_estimated"] == 122
    completed = recent.model_copy(
        update={"overall_status": "COMPLETED", "primary_completion_date": date(2020, 1, 1)}
    )
    assert timeline_status(completed, TODAY)["silent_delay"] is False


def test_unknown_status_flag_and_future_estimated_date():
    study = make_study(
        overall_status="UNKNOWN",
        primary_completion_type="ESTIMATED",
        primary_completion_date=date(2027, 1, 1),
    )
    status = timeline_status(study, TODAY)
    assert status["unknown_status"] is True
    assert status["days_past_estimated"] == 0
    assert status["months_since_update"] == 0  # no last_update_posted


def test_months_between():
    assert months_between(date(2025, 1, 15), date(2025, 2, 14)) == 0
    assert months_between(date(2025, 1, 15), date(2025, 2, 15)) == 1
    assert months_between(date(2025, 3, 1), date(2025, 1, 1)) == 0


# --- outcome comparison --------------------------------------------------------------


def test_identical_outcomes_match():
    registered = [RegisteredOutcome(measure="Change in HbA1c at week 24", time_frame="24 weeks")]
    reported = [ReportedOutcome(title="Change in  HbA1c at Week 24", time_frame="24 weeks")]
    result = compare_primary_outcomes(registered, reported)
    assert result["comparable"] is True
    assert result["pairs"][0]["similarity"] == 1.0
    assert result["pairs"][0]["time_frame_similarity"] == 1.0
    assert result["pairs"][0]["possible_switch"] is False
    assert result["unmatched_registered"] == [] and result["unmatched_reported"] == []
    assert result["max_mismatch"] == 0.0


def test_switched_outcome_is_flagged():
    registered = [RegisteredOutcome(measure="Overall survival at 5 years", time_frame="5 years")]
    reported = [
        ReportedOutcome(title="Number of participants with adverse events", time_frame="1 year")
    ]
    result = compare_primary_outcomes(registered, reported)
    assert result["pairs"][0]["possible_switch"] is True
    assert result["unmatched_registered"] == ["Overall survival at 5 years"]
    assert result["unmatched_reported"] == ["Number of participants with adverse events"]
    assert result["max_mismatch"] > 0.4


def test_count_difference_and_extra_reported_outcome():
    registered = [RegisteredOutcome(measure="Change in HbA1c")]
    reported = [
        ReportedOutcome(title="Change in HbA1c"),
        ReportedOutcome(title="Body weight change"),
    ]
    result = compare_primary_outcomes(registered, reported)
    assert result["count_difference"] == 1
    assert result["unmatched_reported"] == ["Body weight change"]


def test_not_comparable_when_a_list_is_empty():
    registered = [RegisteredOutcome(measure="Change in HbA1c")]
    for reg, rep in ((registered, []), ([], [ReportedOutcome(title="x")])):
        result = compare_primary_outcomes(reg, rep)
        assert result["comparable"] is False
        assert result["pairs"] == []
