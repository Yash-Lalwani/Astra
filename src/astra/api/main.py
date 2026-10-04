from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from astra.api.routes import memory, review, runs, signals, sponsors, system, trials, trust
from astra.config import configure_logging, settings
from astra.db import apply_schema, close_pool, get_pool
from astra.graph.builder import build_graph
from astra.memory.episodic import open_store
from astra.memory.procedural import seed_default_rules


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await get_pool()
    await apply_schema()
    await seed_default_rules()
    app.state.store = await open_store()
    app.state.graph = build_graph(app.state.store)
    yield
    await close_pool()


app = FastAPI(title="Astra API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)
for module in (system, runs, signals, trials, sponsors, review, memory, trust):
    app.include_router(module.router, prefix="/api/v1")
