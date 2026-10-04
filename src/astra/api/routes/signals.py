import uuid

from fastapi import APIRouter, HTTPException

from astra.api.deps import PagingDep
from astra.api.schemas import Page, Signal, to_page
from astra.models import AgentName, ConditionGroup
from astra.queries import signals as signal_queries

router = APIRouter(tags=["signals"])


@router.get("/signals", response_model=Page[Signal])
async def list_signals(
    paging: PagingDep,
    agent: AgentName | None = None,
    signal_type: str | None = None,
    status: str | None = None,
    sponsor: str | None = None,
    condition_group: ConditionGroup | None = None,
    min_confidence: float | None = None,
    run_id: uuid.UUID | None = None,
):
    rows = await signal_queries.list_signals(
        agent=agent,
        signal_type=signal_type,
        status=status,
        sponsor=sponsor,
        condition_group=condition_group,
        min_confidence=min_confidence,
        run_id=str(run_id) if run_id else None,
        limit=paging.limit,
        offset=paging.offset,
    )
    return to_page(rows, Signal)


@router.get("/signals/{signal_id}", response_model=Signal)
async def get_signal(signal_id: uuid.UUID):
    signal = await signal_queries.get_signal(str(signal_id))
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal
