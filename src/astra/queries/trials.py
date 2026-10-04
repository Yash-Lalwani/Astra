from psycopg.types.json import Jsonb

from astra.db import execute_many, fetch_all, fetch_one
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


# Optional filters shared by the tool queries: a NULL parameter means "no filter".
# The sponsor filter is a case-insensitive substring: "lilly" finds "Eli Lilly and Company".
OPTIONAL_FILTERS = """
  (%(condition_group)s::text IS NULL OR condition_group = %(condition_group)s)
  AND (%(sponsor)s::text IS NULL OR sponsor ILIKE '%%' || %(sponsor)s || '%%')
"""


async def search_studies(
    condition_group: str | None,
    sponsor: str | None,
    status: str | None,
    has_results: bool | None,
    phase: str | None,
    limit: int,
) -> list[dict]:
    return await fetch_all(
        f"""
        SELECT nct_id, title, sponsor, condition_group, overall_status, phases,
               start_date, primary_completion_date, primary_completion_type, has_results,
               is_applicable_trial
        FROM studies
        WHERE {OPTIONAL_FILTERS}
          AND (%(status)s::text IS NULL OR overall_status = %(status)s)
          AND (%(has_results)s::boolean IS NULL OR has_results = %(has_results)s)
          AND (%(phase)s::text IS NULL OR %(phase)s = ANY(phases))
        ORDER BY nct_id
        LIMIT %(limit)s
        """,
        {
            "condition_group": condition_group,
            "sponsor": sponsor,
            "status": status,
            "has_results": has_results,
            "phase": phase,
            "limit": limit,
        },
    )


async def get_study(nct_id: str) -> ParsedStudy | None:
    row = await fetch_one("SELECT * FROM studies WHERE nct_id = %s", (nct_id,))
    return ParsedStudy.model_validate(row) if row else None


async def missing_results_candidates(
    condition_group: str | None, sponsor: str | None
) -> list[ParsedStudy]:
    """Completed applicable trials without results; rules.results_due_status decides the rest."""
    rows = await fetch_all(
        f"""
        SELECT * FROM studies
        WHERE {OPTIONAL_FILTERS}
          AND is_applicable_trial AND overall_status = 'COMPLETED' AND NOT has_results
        """,
        {"condition_group": condition_group, "sponsor": sponsor},
    )
    return [ParsedStudy.model_validate(row) for row in rows]


async def studies_with_status(
    statuses: list[str], condition_group: str | None, sponsor: str | None
) -> list[ParsedStudy]:
    rows = await fetch_all(
        f"""
        SELECT * FROM studies
        WHERE {OPTIONAL_FILTERS} AND overall_status = ANY(%(statuses)s)
        """,
        {"condition_group": condition_group, "sponsor": sponsor, "statuses": statuses},
    )
    return [ParsedStudy.model_validate(row) for row in rows]


async def all_studies() -> list[ParsedStudy]:
    return [ParsedStudy.model_validate(row) for row in await fetch_all("SELECT * FROM studies")]


async def existing_nct_ids(nct_ids: list[str]) -> set[str]:
    rows = await fetch_all("SELECT nct_id FROM studies WHERE nct_id = ANY(%s)", (nct_ids,))
    return {row["nct_id"] for row in rows}


async def studies_for_sponsor(sponsor: str) -> list[dict]:
    return await fetch_all(
        """
        SELECT nct_id, title, sponsor, condition_group, overall_status, phases, start_date,
               primary_completion_date, primary_completion_type, has_results, is_applicable_trial
        FROM studies WHERE sponsor = %s
        ORDER BY primary_completion_date DESC NULLS LAST, nct_id
        """,
        (sponsor,),
    )
