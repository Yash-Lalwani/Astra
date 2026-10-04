import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from astra.api.deps import PagingDep, require_admin
from astra.api.schemas import Page, ReviewDecision, ReviewResult, Signal, to_page
from astra.memory.procedural import learn_from_rejection
from astra.models import AgentName, SavedSignal
from astra.queries import signals as signal_queries

logger = logging.getLogger(__name__)
router = APIRouter(tags=["review"])


@router.get("/review/queue", response_model=Page[Signal])
async def review_queue(paging: PagingDep, agent: AgentName | None = None):
    rows = await signal_queries.list_signals(
        status="pending_review", agent=agent, limit=paging.limit, offset=paging.offset
    )
    return to_page(rows, Signal)


@router.post(
    "/review/{signal_id}",
    response_model=ReviewResult,
    dependencies=[Depends(require_admin)],
    responses={
        401: {"description": "Admin key missing or not accepted"},
        404: {"description": "Signal not found"},
        409: {"description": "Signal already reviewed"},
    },
)
async def review(signal_id: uuid.UUID, body: ReviewDecision):
    """Approve, reject or edit a signal. A rejection teaches the agent a new rule."""
    if await signal_queries.get_signal(str(signal_id)) is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    updated = await signal_queries.review_signal(
        str(signal_id),
        status="rejected" if body.decision == "reject" else "approved",
        reason=body.reason,
        edited_summary=body.edited_summary if body.decision == "edit" else None,
    )
    if updated is None:
        raise HTTPException(status_code=409, detail="Signal already reviewed")

    rule_change = None
    if body.decision == "reject":
        # The rejection is saved either way; a failed learning step only loses the new rule.
        try:
            signal = SavedSignal.model_validate(updated)
            rule_change = await learn_from_rejection(signal, body.reason)
        except Exception:
            logger.warning("Learning from rejection of %s failed", signal_id, exc_info=True)
    return ReviewResult(signal=updated, rule_change=rule_change)
