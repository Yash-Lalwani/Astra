from collections import defaultdict
from typing import Literal

from fastapi import APIRouter

from astra.api.deps import PagingDep
from astra.api.schemas import (
    ApprovalPoint,
    ApprovalRate,
    EvalRun,
    GuardrailEventPage,
    Page,
    to_page,
)
from astra.models import AgentName
from astra.queries import evals as eval_queries
from astra.queries import guardrails as guardrail_queries
from astra.queries import signals as signal_queries

router = APIRouter(tags=["trust"])


@router.get("/evals", response_model=Page[EvalRun])
async def list_evals(paging: PagingDep, suite: Literal["trials", "routing"] | None = None):
    return to_page(await eval_queries.list_eval_runs(suite, paging.limit, paging.offset), EvalRun)


def _point(agent: str | None, week, approved: int, rejected: int) -> ApprovalPoint:
    return ApprovalPoint(
        agent=agent,
        week=week,
        approved=approved,
        rejected=rejected,
        approval_rate=approved / (approved + rejected),
    )


@router.get("/metrics/approval-rate", response_model=ApprovalRate)
async def approval_rate(agent: AgentName | None = None):
    """Weekly share of human decisions that approved a signal (an edit counts as approval)."""
    rows = await signal_queries.weekly_approval(agent)
    weekly: dict = defaultdict(lambda: [0, 0])
    for row in rows:
        weekly[row["week"]][0] += row["approved"]
        weekly[row["week"]][1] += row["rejected"]
    return ApprovalRate(
        by_agent=[_point(r["agent"], r["week"], r["approved"], r["rejected"]) for r in rows],
        overall=[_point(None, week, *counts) for week, counts in sorted(weekly.items())],
    )


@router.get("/guardrails/events", response_model=GuardrailEventPage)
async def guardrail_events(
    paging: PagingDep,
    stage: Literal["input", "tool_output", "signal_validation", "citation_check", "usage_limit"]
    | None = None,
):
    """The guardrail log, newest first, plus event counts per stage (across all events)."""
    rows = await guardrail_queries.list_events(stage, paging.limit, paging.offset)
    return GuardrailEventPage(
        items=rows,
        total=rows[0]["total"] if rows else 0,
        counts=await guardrail_queries.counts_by_stage(),
    )
