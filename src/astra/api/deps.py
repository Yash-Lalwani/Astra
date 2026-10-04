"""Shared request dependencies: admin access (guardrail 6), the public run cap (guardrail 5),
paging, and the graph and store built at startup."""

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from astra.config import settings
from astra.queries import runs as run_queries
from astra.queries.guardrails import log_event

AdminKey = Annotated[str | None, Header(alias="X-Admin-Key")]


def is_admin_key(key: str) -> bool:
    return bool(settings.admin_api_key) and secrets.compare_digest(key, settings.admin_api_key)


def require_admin(x_admin_key: AdminKey = None) -> None:
    if not x_admin_key or not is_admin_key(x_admin_key):
        raise HTTPException(status_code=401, detail="Admin key missing or not accepted")


def run_creator(x_admin_key: AdminKey = None) -> str:
    """'admin' for a valid key, 'public' for no key; a wrong key is rejected with 401."""
    if x_admin_key is None:
        return "public"
    require_admin(x_admin_key)
    return "admin"


async def public_cap_reached() -> bool:
    if await run_queries.public_runs_today() < settings.public_daily_run_limit:
        return False
    await log_event(
        None,
        stage="usage_limit",
        action="blocked",
        reason="public daily run limit reached",
        detail={"limit": settings.public_daily_run_limit},
    )
    return True


@dataclass
class Paging:
    limit: int
    offset: int


def paging(
    limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0)] = 0
) -> Paging:
    return Paging(limit, offset)


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.graph


def get_store(request: Request) -> BaseStore:
    return request.app.state.store


PagingDep = Annotated[Paging, Depends(paging)]
GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
StoreDep = Annotated[BaseStore, Depends(get_store)]
