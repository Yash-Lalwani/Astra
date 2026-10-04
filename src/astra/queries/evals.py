from astra.db import fetch_all


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
