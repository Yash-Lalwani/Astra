from psycopg.types.json import Jsonb

from astra.db import execute_many
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
