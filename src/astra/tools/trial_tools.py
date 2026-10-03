"""SQL-backed agent tools. Facts are computed by rules.py; the model only reads them."""

import json
import re
from collections import defaultdict
from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from astra.config import CONDITION_GROUPS
from astra.guardrails.injection import sanitize_external_text
from astra.ingestion.rules import (
    ACTIVE_STATUSES,
    compare_primary_outcomes,
    results_deadline_passed,
    results_due_status,
    timeline_status,
)
from astra.queries import sponsors as sponsor_queries
from astra.queries import trials as trial_queries

MAX_TEXT_CHARS = 1200
MAX_OUTPUT_CHARS = 6000
MAX_LIMIT = 50
MAX_GROUPS = 25
NCT_ID_PATTERN = re.compile(r"^NCT\d{8}$")
STATUSES = {
    "COMPLETED", "TERMINATED", "RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING", "UNKNOWN", "SUSPENDED", "WITHDRAWN",
}  # fmt: skip
PHASES = {"EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"}
GROUP_BY_FIELDS = {"sponsor", "condition_group"}
METRICS = {"missing_results_rate", "silent_delay_rate"}


def clip(text: str | None) -> str | None:
    if text and len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS] + " [...]"
    return text


def to_json(result: dict[str, Any]) -> str:
    """Compact JSON of at most MAX_OUTPUT_CHARS: drops items from the longest list until it fits."""
    text = json.dumps(result, default=str, separators=(",", ":"))
    while len(text) > MAX_OUTPUT_CHARS:
        lists = [key for key, value in result.items() if isinstance(value, list) and value]
        if not lists:
            break
        longest = max(lists, key=lambda key: len(json.dumps(result[key], default=str)))
        result[longest].pop()
        result["truncated"] = True
        text = json.dumps(result, default=str, separators=(",", ":"))
    return text


def check_nct_id(nct_id: str) -> str:
    nct_id = nct_id.strip().upper()
    if not NCT_ID_PATTERN.match(nct_id):
        raise ValueError(f"{nct_id!r} is not an NCT ID; expected e.g. NCT01234567")
    return nct_id


def check_choice(name: str, value: str | None, allowed: set[str] | dict) -> str | None:
    if value is not None and value not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}, got {value!r}")
    return value


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def check_group(condition_group: str | None) -> str | None:
    if condition_group is not None:
        condition_group = condition_group.strip().lower()
    return check_choice("condition_group", condition_group, CONDITION_GROUPS)


def not_found(nct_id: str) -> str:
    return to_json({"nct_id": nct_id, "found": False, "message": "No such trial in the database"})


@tool
async def search_trials(
    condition_group: str | None = None,
    sponsor: str | None = None,
    status: str | None = None,
    has_results: bool | None = None,
    phase: str | None = None,
    limit: int = 20,
) -> str:
    """Search stored trials. All filters are optional.

    condition_group: oncology, cardiovascular, cns_mental_health or metabolic_t2d.
    sponsor: part of the lead sponsor name (case-insensitive).
    status: overall status, e.g. COMPLETED, TERMINATED, RECRUITING, ACTIVE_NOT_RECRUITING, UNKNOWN.
    has_results: whether results are posted on ClinicalTrials.gov.
    phase: e.g. PHASE2, PHASE3, PHASE4.
    Returns basic rows: nct_id, title, sponsor, status, phases, dates, has_results, and
    is_applicable_trial (only applicable trials can have legally overdue results).
    """
    rows = await trial_queries.search_studies(
        condition_group=check_group(condition_group),
        sponsor=sponsor.strip() if sponsor else None,
        status=check_choice("status", status.upper() if status else None, STATUSES),
        has_results=has_results,
        phase=check_choice("phase", phase.upper() if phase else None, PHASES),
        limit=check_limit(limit),
    )
    return to_json({"count": len(rows), "trials": rows})


@tool
async def get_trial(nct_id: str, config: RunnableConfig) -> str:
    """Full details of one trial, plus computed facts: whether it is an FDAAA applicable
    trial, whether results are overdue (and by how many months), and its timeline status."""
    nct_id = check_nct_id(nct_id)
    study = await trial_queries.get_study(nct_id)
    if study is None:
        return not_found(nct_id)
    today = date.today()
    data = study.model_dump(mode="json")
    for field in ("brief_summary", "detailed_description"):
        data[field] = await sanitize_external_text(clip(data[field]), nct_id, config)
    data["facts"] = {
        "is_applicable_trial": study.is_applicable_trial,
        "results_due": results_due_status(study, today),
        "timeline": timeline_status(study, today),
    }
    return to_json(data)


@tool
async def find_missing_results(
    condition_group: str | None = None,
    sponsor: str | None = None,
    min_months_overdue: int = 0,
    limit: int = 25,
) -> str:
    """Applicable trials whose results are overdue: completed, primary completion more than
    12 months ago, and no results posted. Sorted by months_overdue, most overdue first."""
    candidates = await trial_queries.missing_results_candidates(
        check_group(condition_group), sponsor.strip() if sponsor else None
    )
    today = date.today()
    overdue = []
    for study in candidates:
        status = results_due_status(study, today)
        if status["results_due"] and status["months_overdue"] >= min_months_overdue:
            overdue.append(
                {
                    "nct_id": study.nct_id,
                    "title": study.title,
                    "sponsor": study.sponsor,
                    "condition_group": study.condition_group,
                    "phases": study.phases,
                    "enrollment": study.enrollment,
                    "primary_completion_date": study.primary_completion_date,
                    "months_overdue": status["months_overdue"],
                }
            )
    overdue.sort(key=lambda row: row["months_overdue"], reverse=True)
    return to_json({"total_found": len(overdue), "trials": overdue[: check_limit(limit)]})


@tool
async def compare_outcomes(nct_id: str) -> str:
    """Compare a trial's registered primary outcomes with the primary outcomes reported in its
    results section. Each registered outcome gets its best text similarity (0-1);
    possible_switch is true below 0.6. Not comparable when either list is empty."""
    nct_id = check_nct_id(nct_id)
    study = await trial_queries.get_study(nct_id)
    if study is None:
        return not_found(nct_id)
    comparison = compare_primary_outcomes(
        study.registered_primary_outcomes, study.reported_primary_outcomes
    )
    return to_json(
        {
            "nct_id": nct_id,
            "has_results": study.has_results,
            **comparison,
            "registered": [outcome.model_dump() for outcome in study.registered_primary_outcomes],
            "reported": [outcome.model_dump() for outcome in study.reported_primary_outcomes],
        }
    )


@tool
async def find_timeline_issues(
    condition_group: str | None = None, sponsor: str | None = None, limit: int = 25
) -> str:
    """Trials that look silently delayed: still active more than 180 days after their estimated
    primary completion date, or with status UNKNOWN (record not verified for 2+ years).
    Silent delays come first, longest delay first."""
    statuses = sorted(ACTIVE_STATUSES | {"UNKNOWN"})
    candidates = await trial_queries.studies_with_status(
        statuses, check_group(condition_group), sponsor.strip() if sponsor else None
    )
    today = date.today()
    issues = []
    for study in candidates:
        status = timeline_status(study, today)
        if status["silent_delay"] or status["unknown_status"]:
            issues.append(
                {
                    "nct_id": study.nct_id,
                    "title": study.title,
                    "sponsor": study.sponsor,
                    "overall_status": study.overall_status,
                    "primary_completion_date": study.primary_completion_date,
                    "primary_completion_type": study.primary_completion_type,
                    "last_update_posted": study.last_update_posted,
                    **status,
                }
            )
    issues.sort(
        key=lambda row: (
            row["silent_delay"],
            row["days_past_estimated"],
            row["months_since_update"],
        ),
        reverse=True,
    )
    return to_json({"total_found": len(issues), "trials": issues[: check_limit(limit)]})


@tool
async def get_adverse_event_summary(nct_id: str) -> str:
    """Serious adverse events posted in the registry for one trial: the number of participants
    with a serious adverse event and at risk (summed across arms), deaths, and the top serious
    terms by number of participants affected."""
    nct_id = check_nct_id(nct_id)
    study = await trial_queries.get_study(nct_id)
    if study is None:
        return not_found(nct_id)
    if study.adverse_events is None:
        return to_json(
            {
                "nct_id": nct_id,
                "has_results": study.has_results,
                "adverse_events": None,
                "message": "This trial has no posted results section with adverse events.",
            }
        )
    return to_json(
        {
            "nct_id": nct_id,
            "has_results": study.has_results,
            "adverse_events": study.adverse_events.model_dump(),
        }
    )


@tool
async def get_sponsor_profile(sponsor: str) -> str:
    """Reporting profile of one lead sponsor (exact name, case-insensitive): total trials,
    applicable completed trials with results due, results posted, missing results,
    compliance_rate (null below 3 applicable completed trials) and average reporting delay."""
    profile = await sponsor_queries.get_profile(sponsor.strip())
    if profile is None:
        message = "No sponsor with this exact name; use search_trials or list_sponsors to find it."
        return to_json({"sponsor": sponsor, "found": False, "message": message})
    return to_json({"found": True, **profile})


@tool
async def list_sponsors(
    condition_group: str | None = None,
    min_studies: int = 3,
    order_by: str = "compliance_rate",
    limit: int = 20,
) -> str:
    """Sponsor profiles with at least min_studies trials, optionally only sponsors with a trial
    in condition_group. order_by: compliance_rate (lowest first), missing_results or
    total_studies (highest first)."""
    if min_studies < 1:
        raise ValueError("min_studies must be at least 1")
    rows = await sponsor_queries.list_profiles(
        condition_group=check_group(condition_group),
        min_studies=min_studies,
        order_by=check_choice("order_by", order_by, sponsor_queries.SPONSOR_ORDER),
        limit=check_limit(limit),
    )
    return to_json({"count": len(rows), "sponsors": rows})


@tool
async def cross_study_stats(group_by: str, metric: str, min_group_size: int = 3) -> str:
    """Compare groups of trials on one metric to find outliers.

    group_by: sponsor or condition_group.
    metric: missing_results_rate (share of applicable completed trials past their results
    deadline that posted no results) or silent_delay_rate (share of all trials that are
    silently delayed).
    Returns each group's value and size, the overall average across all trials, and each
    group's deviation_from_mean, largest first. Groups smaller than min_group_size are left out.
    """
    check_choice("group_by", group_by, GROUP_BY_FIELDS)
    check_choice("metric", metric, METRICS)
    today = date.today()
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # group -> [hits, size]
    for study in await trial_queries.all_studies():
        if metric == "missing_results_rate":
            if not results_deadline_passed(study, today):
                continue
            hit = not study.has_results
        else:
            hit = timeline_status(study, today)["silent_delay"]
        group_counts = counts[getattr(study, group_by)]
        group_counts[0] += hit
        group_counts[1] += 1

    total_hits = sum(hits for hits, _ in counts.values())
    total_size = sum(size for _, size in counts.values())
    overall = total_hits / total_size if total_size else 0.0
    groups = [
        {
            "group": group,
            "value": round(hits / size, 3),
            "hits": hits,
            "group_size": size,
            "deviation_from_mean": round(hits / size - overall, 3),
        }
        for group, (hits, size) in counts.items()
        if size >= min_group_size
    ]
    groups.sort(key=lambda row: row["deviation_from_mean"], reverse=True)
    return to_json(
        {
            "group_by": group_by,
            "metric": metric,
            "overall_average": round(overall, 3),
            "groups_compared": len(groups),
            "groups": groups[:MAX_GROUPS],
        }
    )
