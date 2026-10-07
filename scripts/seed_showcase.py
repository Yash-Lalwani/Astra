"""Run the fixed showcase tasks through the real graph and mark them is_showcase, so visitors can
replay them through /stream without using any LLM quota.

Run it from your machine against the production database after deploying. A task that already has
a completed showcase run is skipped, so the script is safe to run again.

Usage: uv run python scripts/seed_showcase.py
"""

import asyncio

from astra.config import configure_logging
from astra.db import apply_schema, close_pool
from astra.graph.builder import build_graph
from astra.memory.episodic import open_store
from astra.memory.procedural import seed_default_rules
from astra.queries import runs as run_queries
from astra.runner import stream_run

SHOWCASE_TASKS = [
    "Find oncology trials that finished over a year ago but never posted results",
    "Check cardiovascular trials with posted results for outcome switching",
    "Which metabolic/type 2 diabetes sponsors have the weakest reporting record?",
    "Look for silent delays in CNS and mental health trials",
    "Scan oncology trials with results for safety reporting gaps",
]


async def main() -> None:
    configure_logging()
    try:
        await apply_schema()
        await seed_default_rules()
        graph = build_graph(await open_store())
        existing = await run_queries.list_runs(True, "completed", limit=100, offset=0)
        done = {run["task"] for run in existing}
        for task in SHOWCASE_TASKS:
            if task in done:
                print(f"skip (already a showcase run): {task}")
                continue
            run_id = await run_queries.create_run(task, created_by="admin", is_showcase=True)
            await run_queries.claim_run(run_id)
            print(f"\n{task}\n  run {run_id}")
            async for event in stream_run(graph, run_id):
                if event["type"] in ("routing", "agent_finished", "review_gate", "run_finished"):
                    detail = {k: v for k, v in event.items() if k not in ("type", "ts", "run_id")}
                    print(f"  {event['type']}: {str(detail)[:150]}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
