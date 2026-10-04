from fastapi import APIRouter, Response

from astra.agents.registry import AGENTS
from astra.api.deps import GraphDep
from astra.api.schemas import AgentInfo, GraphDiagram, Health, Page, Stats
from astra.config import settings
from astra.db import database_ok
from astra.queries import rules as rule_queries
from astra.queries import signals as signal_queries

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Health, responses={503: {"model": Health}})
async def health(response: Response):
    database = "ok" if await database_ok() else "error"
    # Layer-Engine is connected in Phase 5; until then a configured URL cannot be "ok".
    layer = "error" if settings.layer_enabled else "disabled"
    if database != "ok":
        response.status_code = 503
    return Health(status="ok" if database == "ok" else "error", database=database, layer=layer)


@router.get("/stats", response_model=Stats)
async def stats():
    return await signal_queries.home_stats()


@router.get("/agents", response_model=Page[AgentInfo])
async def list_agents():
    rule_counts = await rule_queries.rule_counts()
    agents = [
        AgentInfo(
            name=config.name,
            display_name=config.display_name,
            description=config.description,
            signal_type=config.signal_type,
            level=config.level,
            threshold=config.threshold,
            tools=[tool.name for tool in config.tools],
            rule_count=rule_counts.get(config.name, 0),
        )
        for config in AGENTS.values()
    ]
    return Page[AgentInfo](items=agents, total=len(agents))


@router.get("/graph", response_model=GraphDiagram)
async def graph_diagram(graph: GraphDep):
    return GraphDiagram(mermaid=graph.get_graph(xray=1).draw_mermaid())
