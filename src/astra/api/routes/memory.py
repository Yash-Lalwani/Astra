from typing import Annotated

from fastapi import APIRouter, Query

from astra.api.deps import StoreDep
from astra.api.schemas import Episode, Page, Rule
from astra.memory.episodic import find_episodes
from astra.memory.procedural import get_rules
from astra.models import AgentName

router = APIRouter(tags=["memory"])


@router.get("/memory/rules", response_model=Page[Rule])
async def list_rules(agent: AgentName):
    """All of the agent's rules, default and learned, oldest first."""
    rules = await get_rules(agent)
    return Page[Rule](items=rules, total=len(rules))


@router.get("/memory/episodes", response_model=Page[Episode])
async def list_episodes(
    store: StoreDep,
    agent: AgentName | None = None,
    query: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Semantic search over past runs; the most recent ones when there is no query."""
    episodes = await find_episodes(store, agent, query, limit)
    return Page[Episode](items=episodes, total=len(episodes))
