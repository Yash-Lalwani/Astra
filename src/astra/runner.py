"""Execute a run: stream the graph's events live, then save totals and events on the run row."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from langgraph.graph.state import CompiledStateGraph

from astra.config import settings
from astra.queries import runs as run_queries

logger = logging.getLogger(__name__)

# The events whose token counts make up a run's total (run_finished repeats the total).
TOKEN_EVENTS = {"routing", "agent_finished", "brief"}


def _stamp(event: dict, run_id: str) -> dict:
    return {**event, "ts": datetime.now(UTC).isoformat(), "run_id": run_id}


def _summary(events: list[dict]) -> dict:
    """Run totals, all derived from the events (tokens are counted once, in the events)."""
    finished = [event for event in events if event["type"] == "agent_finished"]
    gate = next((event for event in events if event["type"] == "review_gate"), None)
    return {
        "status": "blocked" if any(e["type"] == "input_blocked" for e in events) else "completed",
        "input_tokens": sum(e["input_tokens"] for e in events if e["type"] in TOKEN_EVENTS),
        "output_tokens": sum(e["output_tokens"] for e in events if e["type"] in TOKEN_EVENTS),
        "signals_count": gate["auto_approved"] + gate["pending_review"] if gate else 0,
        "pending_review_count": gate["pending_review"] if gate else 0,
        "agent_stats": {
            event["agent"]: {
                key: event[key]
                for key in (
                    "steps",
                    "tool_calls",
                    "input_tokens",
                    "output_tokens",
                    "duration_ms",
                    "signals",
                    "error",
                )
            }
            for event in finished
        },  # fmt: skip
    }


async def stream_run(graph: CompiledStateGraph, run_id: uuid.UUID | str) -> AsyncIterator[dict]:
    """Run a run live, yielding each event; the events are saved for replay.
    The caller first claims the run (run_queries.claim_run), so it is never started twice."""
    run_id = str(run_id)
    run = await run_queries.get_run(run_id)
    logger.info("Run %s started: %s", run_id, run["task"])
    started = time.perf_counter()
    events: list[dict] = []

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        async for event in graph.astream(
            {"run_id": run_id, "task": run["task"], "condition_group": run["condition_group"]},
            config={"run_name": "astra_run", "tags": ["astra"], "metadata": {"run_id": run_id}},
            stream_mode="custom",
        ):
            events.append(_stamp(event, run_id))
            yield events[-1]
    except (asyncio.CancelledError, GeneratorExit):
        # The client went away mid-run: record the failure, nobody is left to tell.
        await run_queries.finish_run(run_id, "failed", 0, 0, {}, events, elapsed_ms(),
                                     error="client disconnected")  # fmt: skip
        raise
    except Exception as error:
        logger.exception("Run %s failed", run_id)
        await run_queries.finish_run(run_id, "failed", 0, 0, {}, events, elapsed_ms(),
                                     error=str(error))  # fmt: skip
        yield _stamp({"type": "run_failed", "error": str(error)}, run_id)
        return

    summary = _summary(events)
    final = _stamp(
        {
            "type": "run_finished",
            **{key: summary[key] for key in ("status", "signals_count", "pending_review_count",
                                              "input_tokens", "output_tokens")},
            "duration_ms": elapsed_ms(),
        },
        run_id,
    )  # fmt: skip
    events.append(final)
    await run_queries.finish_run(
        run_id,
        summary["status"],
        summary["input_tokens"],
        summary["output_tokens"],
        summary["agent_stats"],
        events,
        final["duration_ms"],
    )
    logger.info("Run %s finished: %s", run_id, summary["status"])
    yield final


async def replay_run(run_id: uuid.UUID | str) -> AsyncIterator[dict]:
    """Yield a finished run's stored events again, paced like a live run, using no LLM calls."""
    run = await run_queries.get_run(str(run_id))
    for event in run["events"]:
        yield event
        await asyncio.sleep(settings.replay_delay_ms / 1000)
