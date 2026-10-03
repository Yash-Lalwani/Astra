from psycopg.types.json import Jsonb

from astra.db import execute_many, fetch_all
from astra.models import ParsedStudy

STUDY_COLUMNS = (
    "nct_id", "condition_group", "title", "brief_summary", "detailed_description",
    "conditions", "interventions", "study_type", "phases", "enrollment", "overall_status",
    "why_stopped", "sponsor", "sponsor_class", "start_date", "primary_completion_date",
    "primary_completion_type", "completion_date", "completion_type", "first_posted",
    "last_update_posted", "results_first_posted", "has_results", "is_fda_regulated",
    "is_applicable_trial", "registered_primary_outcomes",
    "reported_primary_outcomes", "adverse_events", "reference_pmids",
)  # fmt: skip
JSONB_COLUMNS = {
    "interventions",
    "registered_primary_outcomes",
    "reported_primary_outcomes",
    "adverse_events",
}

# Column names come from the fixed tuple above, never from input.
UPSERT_STUDY = f"""
INSERT INTO studies ({", ".join(STUDY_COLUMNS)})
VALUES ({", ".join(f"%({column})s" for column in STUDY_COLUMNS)})
ON CONFLICT (nct_id) DO UPDATE SET
  {", ".join(f"{column} = EXCLUDED.{column}" for column in STUDY_COLUMNS[1:])},
  ingested_at = now()
"""


def _study_params(study: ParsedStudy) -> dict:
    params = study.model_dump()
    for column in JSONB_COLUMNS:
        params[column] = Jsonb(params[column]) if params[column] is not None else None
    return params


async def upsert_studies(studies: list[ParsedStudy]) -> None:
    await execute_many(UPSERT_STUDY, [_study_params(study) for study in studies])


async def counts_by_group_and_status() -> list[dict]:
    return await fetch_all(
        """
        SELECT condition_group, overall_status, count(*) AS trials,
               count(*) FILTER (WHERE has_results) AS with_results,
               count(*) FILTER (WHERE is_applicable_trial) AS applicable
        FROM studies
        GROUP BY condition_group, overall_status
        ORDER BY condition_group, trials DESC
        """
    )
