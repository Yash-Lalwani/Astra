import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from sse_starlette import EventSourceResponse

from astra.api.deps import GraphDep, PagingDep, public_cap_reached, run_creator
from astra.api.schemas import (
    Page,
    RunCapReached,
    RunCreate,
    RunCreated,
    RunDetail,
    RunSummary,
    to_page,
)
from astra.config import settings
from astra.queries import runs as run_queries
from astra.queries import signals as signal_queries
from astra.runner import replay_run, stream_run

router = APIRouter(tags=["runs"])


async def _run_or_404(run_id: uuid.UUID) -> dict:
    run = await run_queries.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post(
    "/runs",
    response_model=RunCreated,
    status_code=201,
    responses={429: {"model": RunCapReached}, 401: {"description": "Admin key not accepted"}},
)
async def create_run(body: RunCreate, created_by: Annotated[str, Depends(run_creator)]):
    """Queue a run. The live run starts when a client opens its /stream."""
    if created_by == "public" and await public_cap_reached():
        cap = RunCapReached(
            message="Today's live runs are used up. Watch a showcase run instead.",
            limit=settings.public_daily_run_limit,
        )
        return JSONResponse(status_code=429, content=cap.model_dump())
    run_id = await run_queries.create_run(body.task, created_by, body.condition_group)
    return RunCreated(run_id=run_id, status="queued")


@router.get("/runs", response_model=Page[RunSummary])
async def list_runs(paging: PagingDep, showcase: bool | None = None, status: str | None = None):
    rows = await run_queries.list_runs(showcase, status, paging.limit, paging.offset)
    return to_page(rows, RunSummary)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID):
    run = await _run_or_404(run_id)
    signals = await signal_queries.list_signals(run_id=str(run_id))
    return RunDetail.model_validate({**run, "signals": signals})


def _as_sse(events):
    async def stream():
        async for event in events:
            yield {"event": event["type"], "data": json.dumps(event, default=str)}

    return EventSourceResponse(stream())


@router.get(
    "/runs/{run_id}/stream",
    responses={
        200: {"content": {"text/event-stream": {}}},
        409: {"description": "Run in progress"},
    },
)
async def stream(run_id: uuid.UUID, graph: GraphDep):
    """Server-sent events: a queued run runs live; a finished run replays its stored events."""
    run = await _run_or_404(run_id)
    if run["status"] == "running":
        raise HTTPException(status_code=409, detail="Run in progress")
    if run["status"] != "queued":
        return _as_sse(replay_run(run_id))
    if not await run_queries.claim_run(run_id):  # another client started it a moment ago
        raise HTTPException(status_code=409, detail="Run in progress")
    return _as_sse(stream_run(graph, run_id))


@router.get(
    "/runs/{run_id}/brief.md",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def download_brief(run_id: uuid.UUID):
    run = await _run_or_404(run_id)
    if not run["brief"]:
        raise HTTPException(status_code=404, detail="This run has no brief yet")
    rows = [
        f"| {s['agent']} | {s['nct_id'] or s['sponsor']} | {s['title']} | "
        f"{s['confidence']:.2f} | {s['status']} |"
        for s in await signal_queries.list_signals(run_id=str(run_id))
    ]
    table = "| Agent | Trial or sponsor | Title | Confidence | Status |\n|---|---|---|---|---|"
    markdown = f"{run['brief']}\n\n## Signals\n\n{table}\n" + "\n".join(rows) + "\n"
    return PlainTextResponse(
        markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="astra-brief-{run_id}.md"'},
    )
