import logging
from typing import Any, Literal

from psycopg.types.json import Jsonb

from astra.db import execute, fetch_all

logger = logging.getLogger(__name__)

Stage = Literal["input", "tool_output", "signal_validation", "citation_check", "usage_limit"]
Action = Literal["blocked", "dropped", "capped", "sanitized", "stopped"]


async def log_event(
    run_id: str | None,
    stage: Stage,
    action: Action,
    reason: str,
    agent: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    await execute(
        """
        INSERT INTO guardrail_events (run_id, stage, agent, action, reason, detail)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (run_id, stage, agent, action, reason, Jsonb(detail or {})),
    )
    logger.info("Guardrail %s/%s (agent %s, run %s): %s", stage, action, agent, run_id, reason)


async def list_events(stage: str | None, limit: int, offset: int) -> list[dict]:
    """Newest first; every row carries the total match count as `total`."""
    return await fetch_all(
        """
        SELECT *, count(*) OVER () AS total FROM guardrail_events
        WHERE %(stage)s::text IS NULL OR stage = %(stage)s
        ORDER BY created_at DESC, event_id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"stage": stage, "limit": limit, "offset": offset},
    )


async def counts_by_stage() -> dict[str, int]:
    rows = await fetch_all("SELECT stage, count(*) AS events FROM guardrail_events GROUP BY stage")
    return {row["stage"]: row["events"] for row in rows}
