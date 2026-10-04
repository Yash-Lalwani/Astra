"""Episodic memory: what each agent did in past runs, searchable by meaning.

LangMem has no episodic utilities, so this uses LangGraph's store directly.
"""

from datetime import UTC, datetime

from langgraph.store.base import BaseStore
from langgraph.store.postgres import AsyncPostgresStore

from astra import llm
from astra.config import settings
from astra.db import get_pool
from astra.models import AgentResult, SavedSignal

MAX_NOTES_CHARS = 1000


async def open_store() -> AsyncPostgresStore:
    """The store on the shared pool, with a vector index over each episode's summary."""
    store = AsyncPostgresStore(
        await get_pool(),
        index={"dims": settings.embedding_dims, "embed": llm.embeddings(), "fields": ["summary"]},
    )
    await store.setup()
    return store


def episode_summary(task: str, signals: list[SavedSignal], notes: str) -> str:
    flagged = "; ".join(
        f"{signal.nct_id or signal.sponsor} ({signal.signal_type}, "
        f"confidence {signal.confidence:.2f}, {signal.status})"
        for signal in signals
    )
    return f"Task: {task}\nFlagged: {flagged or 'nothing'}\nNotes: {notes[:MAX_NOTES_CHARS]}"


async def save_episode(
    store: BaseStore, run_id: str, task: str, result: AgentResult, signals: list[SavedSignal]
) -> None:
    await store.aput(
        ("episodes", result.agent),
        run_id,
        {
            "run_id": run_id,
            "task": task,
            "created_at": datetime.now(UTC).isoformat(),
            "summary": episode_summary(task, signals, result.error or result.notes),
            "signals": [
                {
                    "signal_id": str(signal.signal_id),
                    "nct_id": signal.nct_id,
                    "sponsor": signal.sponsor,
                    "title": signal.title,
                    "confidence": signal.confidence,
                }
                for signal in signals
            ],
        },
    )


async def similar_episodes(store: BaseStore, agent: str, task: str, limit: int = 3) -> list[str]:
    """Summaries of the agent's past runs most similar to this task."""
    items = await store.asearch(("episodes", agent), query=task, limit=limit)
    return [item.value["summary"] for item in items]
