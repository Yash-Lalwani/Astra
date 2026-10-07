from psycopg.types.json import Jsonb

from astra.db import execute, fetch_all


async def list_eval_runs(suite: str | None, limit: int, offset: int) -> list[dict]:
    """Newest first; every row carries the total match count as `total`."""
    return await fetch_all(
        """
        SELECT *, count(*) OVER () AS total FROM eval_runs
        WHERE %(suite)s::text IS NULL OR suite = %(suite)s
        ORDER BY created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"suite": suite, "limit": limit, "offset": offset},
    )


async def insert_eval_run(suite: str, models: dict, dataset_size: int, metrics: dict) -> None:
    await execute(
        "INSERT INTO eval_runs (suite, models, dataset_size, metrics) VALUES (%s, %s, %s, %s)",
        (suite, Jsonb(models), dataset_size, Jsonb(metrics)),
    )
