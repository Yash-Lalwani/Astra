from typing import Any, Literal

from psycopg.types.json import Jsonb

from astra.db import execute

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
