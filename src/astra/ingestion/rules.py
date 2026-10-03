"""Deterministic fact functions. The tools compute facts with these; the LLM only judges them."""

import difflib
import re
from datetime import date

from astra.models import ParsedStudy, RegisteredOutcome, ReportedOutcome

EARLY_PHASES = {"EARLY_PHASE1", "PHASE1"}
ACTIVE_STATUSES = {
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
}
SILENT_DELAY_DAYS = 180
OUTCOME_MATCH_THRESHOLD = 0.6


def months_between(start: date, end: date) -> int:
    """Whole calendar months from start to end (0 if end is not after start)."""
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year + 1, day=28)


def is_applicable_trial(study: ParsedStudy) -> bool:
    """Approximation of an FDAAA 801 "applicable clinical trial".

    True when the study is interventional, has a phase beyond Phase 1, and is FDA regulated.
    The real legal test has more conditions than the public registry exposes.
    """
    return (
        study.study_type == "INTERVENTIONAL"
        and any(phase not in EARLY_PHASES for phase in study.phases)
        and study.is_fda_regulated
    )


def results_deadline_passed(study: ParsedStudy, today: date) -> bool:
    """Approximation of the FDAAA results deadline: a completed applicable trial must post
    results within 12 months of its actual primary completion date. True once that deadline
    has passed, whether or not results were posted.
    """
    return bool(
        study.is_applicable_trial
        and study.overall_status == "COMPLETED"
        and study.primary_completion_type == "ACTUAL"
        and study.primary_completion_date
        and today > one_year_after(study.primary_completion_date)
    )


def results_due_status(study: ParsedStudy, today: date) -> dict:
    """Results are overdue when the deadline has passed and none are posted. Extensions and
    certifications of delay are not visible in the public API, so this can over-flag.
    """
    if study.has_results or not results_deadline_passed(study, today):
        return {"results_due": False, "months_overdue": 0}
    deadline = one_year_after(study.primary_completion_date)
    return {"results_due": True, "months_overdue": months_between(deadline, today)}


def timeline_status(study: ParsedStudy, today: date) -> dict:
    """Approximation of a "silent delay": an active trial whose estimated primary completion
    date passed more than 180 days ago without the record being updated to an actual date.
    UNKNOWN status means CT.gov has not seen the record verified for 2+ years.
    """
    days_past_estimated = 0
    if study.primary_completion_type == "ESTIMATED" and study.primary_completion_date:
        days_past_estimated = max((today - study.primary_completion_date).days, 0)
    months_since_update = (
        months_between(study.last_update_posted, today) if study.last_update_posted else 0
    )
    return {
        "silent_delay": study.overall_status in ACTIVE_STATUSES
        and days_past_estimated > SILENT_DELAY_DAYS,
        "days_past_estimated": days_past_estimated,
        "months_since_update": months_since_update,
        "unknown_status": study.overall_status == "UNKNOWN",
    }


def _normalise(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _similarity(left: str | None, right: str | None) -> float:
    return difflib.SequenceMatcher(None, _normalise(left), _normalise(right)).ratio()


def compare_primary_outcomes(
    registered: list[RegisteredOutcome], reported: list[ReportedOutcome]
) -> dict:
    """Approximate check for outcome switching by text similarity.

    The public API has no registry version history, so this compares the registered primary
    outcomes with the primary outcomes reported in the results section, not old protocol
    versions with new ones. A low score is a lead for a human, not proof of switching.
    """
    result: dict = {
        "comparable": bool(registered and reported),
        "registered_count": len(registered),
        "reported_count": len(reported),
        "count_difference": len(reported) - len(registered),
        "pairs": [],
        "unmatched_registered": [],
        "unmatched_reported": [],
        "max_mismatch": 0.0,
    }
    if not result["comparable"]:
        return result

    matched_reported: set[int] = set()
    for outcome in registered:
        scores = [_similarity(outcome.measure, candidate.title) for candidate in reported]
        best_index = max(range(len(reported)), key=scores.__getitem__)
        best = reported[best_index]
        similarity = scores[best_index]
        possible_switch = similarity < OUTCOME_MATCH_THRESHOLD
        result["pairs"].append(
            {
                "registered": outcome.measure,
                "best_reported": best.title,
                "similarity": round(similarity, 2),
                "time_frame_similarity": round(_similarity(outcome.time_frame, best.time_frame), 2),
                "possible_switch": possible_switch,
            }
        )
        if possible_switch:
            result["unmatched_registered"].append(outcome.measure)
        else:
            matched_reported.add(best_index)

    result["unmatched_reported"] = [
        outcome.title for index, outcome in enumerate(reported) if index not in matched_reported
    ]
    result["max_mismatch"] = round(max(1 - pair["similarity"] for pair in result["pairs"]), 2)
    return result
