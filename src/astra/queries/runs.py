import uuid
from typing import Any

from psycopg.types.json import Jsonb

from astra.db import execute, fetch_all, fetch_one


async def create_run(
    task: str,
    created_by: str = "public",
    condition_group: str | None = None,
    is_showcase: bool = False,
) -> uuid.UUID:
    row = await fetch_one(
        """
        INSERT INTO runs (task, created_by, condition_group, is_showcase)
        VALUES (%s, %s, %s, %s) RETURNING run_id
        """,
        (task, created_by, condition_group, is_showcase),
    )
    return row["run_id"]


async def get_run(run_id: uuid.UUID | str) -> dict | None:
    return await fetch_one("SELECT * FROM runs WHERE run_id = %s", (run_id,))


async def claim_run(run_id: uuid.UUID | str) -> bool:
    """Mark a queued run as running. False when it was not queued (already started or done),
    so two streams can never start the same run."""
    row = await fetch_one(
        """
        UPDATE runs SET status = 'running', started_at = now()
        WHERE run_id = %s AND status = 'queued' RETURNING run_id
        """,
        (run_id,),
    )
    return row is not None


async def public_runs_today() -> int:
    row = await fetch_one(
        """
        SELECT count(*) AS runs FROM runs
        WHERE created_by = 'public' AND created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                                                    AT TIME ZONE 'UTC'
        """
    )
    return row["runs"]


async def list_runs(
    showcase: bool | None, status: str | None, limit: int, offset: int
) -> list[dict]:
    """Newest first; every row carries the total match count as `total`."""
    return await fetch_all(
        """
        SELECT *, count(*) OVER () AS total FROM runs
        WHERE (%(showcase)s::boolean IS NULL OR is_showcase = %(showcase)s)
          AND (%(status)s::text IS NULL OR status = %(status)s)
        ORDER BY created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"showcase": showcase, "status": status, "limit": limit, "offset": offset},
    )


async def save_routing(
    run_id: str, agents: list[str], reason: str, condition_group: str | None
) -> None:
    await execute(
        """
        UPDATE runs SET selected_agents = %s, routing_reason = %s, condition_group = %s
        WHERE run_id = %s
        """,
        (agents, reason, condition_group, run_id),
    )


async def save_counts(run_id: str, signals_count: int, pending_review_count: int) -> None:
    await execute(
        "UPDATE runs SET signals_count = %s, pending_review_count = %s WHERE run_id = %s",
        (signals_count, pending_review_count, run_id),
    )


async def save_brief(run_id: str, brief: str) -> None:
    await execute("UPDATE runs SET brief = %s WHERE run_id = %s", (brief, run_id))


async def finish_run(
    run_id: uuid.UUID | str,
    status: str,
    input_tokens: int,
    output_tokens: int,
    agent_stats: dict[str, Any],
    events: list[dict],
    duration_ms: int,
    error: str | None = None,
) -> None:
    await execute(
        """
        UPDATE runs SET status = %s, input_tokens = %s, output_tokens = %s, agent_stats = %s,
               events = %s, duration_ms = %s, error = %s, finished_at = now()
        WHERE run_id = %s
        """,
        (
            status,
            input_tokens,
            output_tokens,
            Jsonb(agent_stats),
            Jsonb(events),
            duration_ms,
            error,
            run_id,
        ),
    )
