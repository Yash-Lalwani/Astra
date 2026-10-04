from psycopg.types.json import Jsonb

from astra.db import execute_many, fetch_all, fetch_one
from astra.models import SavedSignal


async def insert_signals(run_id: str, signals: list[SavedSignal]) -> None:
    await execute_many(
        """
        INSERT INTO signals (signal_id, run_id, agent, signal_type, nct_id, sponsor,
                             related_nct_ids, title, summary, evidence, confidence, threshold,
                             citation_verified, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                signal.signal_id,
                run_id,
                signal.agent,
                signal.signal_type,
                signal.nct_id,
                signal.sponsor,
                signal.related_nct_ids,
                signal.title,
                signal.summary,
                Jsonb([item.model_dump() for item in signal.evidence]),
                signal.confidence,
                signal.threshold,
                signal.citation_verified,
                signal.status,
            )
            for signal in signals
        ],
    )


async def list_signals(
    *,
    agent: str | None = None,
    signal_type: str | None = None,
    status: str | None = None,
    sponsor: str | None = None,
    condition_group: str | None = None,
    min_confidence: float | None = None,
    run_id: str | None = None,
    nct_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Newest first; every row carries the total match count as `total`. The sponsor filter is a
    case-insensitive substring; condition_group comes from the signal's trial."""
    return await fetch_all(
        """
        SELECT signals.*, count(*) OVER () AS total
        FROM signals LEFT JOIN studies ON studies.nct_id = signals.nct_id
        WHERE (%(agent)s::text IS NULL OR signals.agent = %(agent)s)
          AND (%(signal_type)s::text IS NULL OR signals.signal_type = %(signal_type)s)
          AND (%(status)s::text IS NULL OR signals.status = %(status)s)
          AND (%(sponsor)s::text IS NULL OR signals.sponsor ILIKE '%%' || %(sponsor)s || '%%')
          AND (%(condition_group)s::text IS NULL OR studies.condition_group = %(condition_group)s)
          AND (%(min_confidence)s::real IS NULL OR signals.confidence >= %(min_confidence)s)
          AND (%(run_id)s::uuid IS NULL OR signals.run_id = %(run_id)s)
          AND (%(nct_id)s::text IS NULL OR signals.nct_id = %(nct_id)s)
        ORDER BY signals.created_at DESC, signals.signal_id
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {
            "agent": agent,
            "signal_type": signal_type,
            "status": status,
            "sponsor": sponsor,
            "condition_group": condition_group,
            "min_confidence": min_confidence,
            "run_id": run_id,
            "nct_id": nct_id,
            "limit": limit,
            "offset": offset,
        },
    )


async def get_signal(signal_id: str) -> dict | None:
    return await fetch_one("SELECT * FROM signals WHERE signal_id = %s", (signal_id,))


async def signals_for_sponsor(sponsor: str) -> list[dict]:
    """Signals about the sponsor itself or about any of its trials."""
    return await fetch_all(
        """
        SELECT * FROM signals
        WHERE sponsor = %(sponsor)s
           OR nct_id IN (SELECT nct_id FROM studies WHERE sponsor = %(sponsor)s)
        ORDER BY created_at DESC
        """,
        {"sponsor": sponsor},
    )


async def review_signal(
    signal_id: str, status: str, reason: str | None, edited_summary: str | None
) -> dict | None:
    """Record a human decision. None when the signal was already decided by a human."""
    return await fetch_one(
        """
        UPDATE signals SET
          status = %(status)s,
          review_reason = %(reason)s,
          reviewed_at = now(),
          edited = %(edited_summary)s::text IS NOT NULL,
          original_summary = CASE WHEN %(edited_summary)s::text IS NOT NULL
                                  THEN summary END,
          summary = coalesce(%(edited_summary)s, summary)
        WHERE signal_id = %(signal_id)s AND status IN ('auto_approved', 'pending_review')
        RETURNING *
        """,
        {
            "signal_id": signal_id,
            "status": status,
            "reason": reason,
            "edited_summary": edited_summary,
        },
    )


async def home_stats() -> dict:
    return await fetch_one(
        """
        SELECT
          (SELECT count(*) FROM studies) AS trials,
          (SELECT count(*) FROM papers WHERE NOT is_synthetic) AS papers,
          (SELECT count(*) FROM sponsor_profiles) AS sponsors,
          (SELECT count(*) FROM signals) AS signals_total,
          (SELECT count(*) FROM signals WHERE status = 'pending_review') AS signals_pending_review,
          (SELECT count(*) FILTER (WHERE status = 'approved')::real / nullif(count(*), 0)
           FROM signals WHERE reviewed_at IS NOT NULL) AS human_approval_rate,
          (SELECT count(*) FROM runs WHERE status = 'completed') AS runs_completed,
          (SELECT max(ingested_at) FROM studies) AS last_ingested_at
        """
    )


async def weekly_approval(agent: str | None) -> list[dict]:
    """Human decisions per agent and week (an edit counts as an approval)."""
    return await fetch_all(
        """
        SELECT agent, date_trunc('week', reviewed_at)::date AS week,
               count(*) FILTER (WHERE status = 'approved') AS approved,
               count(*) FILTER (WHERE status = 'rejected') AS rejected
        FROM signals
        WHERE reviewed_at IS NOT NULL AND (%(agent)s::text IS NULL OR agent = %(agent)s)
        GROUP BY agent, week
        ORDER BY week, agent
        """,
        {"agent": agent},
    )
