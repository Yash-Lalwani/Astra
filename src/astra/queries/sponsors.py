from astra.db import execute, fetch_all, fetch_one

MIN_TRIALS_FOR_RATE = 3

# "Results due" mirrors rules.results_due_status without the has_results condition: a completed
# applicable trial whose actual primary completion date is more than 12 months ago.
RECOMPUTE_PROFILES = """
WITH per_sponsor AS (
  SELECT
    sponsor,
    max(sponsor_class) AS sponsor_class,
    count(*) AS total_studies,
    count(*) FILTER (WHERE results_due) AS applicable_completed,
    count(*) FILTER (WHERE results_due AND has_results) AS results_posted,
    avg(results_first_posted - primary_completion_date) FILTER (
      WHERE results_first_posted IS NOT NULL
        AND primary_completion_date IS NOT NULL
        AND primary_completion_type = 'ACTUAL'
    ) AS avg_reporting_delay_days
  FROM (
    SELECT *,
           is_applicable_trial
             AND overall_status = 'COMPLETED'
             AND primary_completion_type = 'ACTUAL'
             AND primary_completion_date < current_date - interval '12 months' AS results_due
    FROM studies
  ) AS flagged
  GROUP BY sponsor
)
INSERT INTO sponsor_profiles (
  sponsor, sponsor_class, total_studies, applicable_completed, results_posted,
  missing_results, compliance_rate, avg_reporting_delay_days, updated_at
)
SELECT
  sponsor, sponsor_class, total_studies, applicable_completed, results_posted,
  applicable_completed - results_posted,
  CASE WHEN applicable_completed >= %(min_trials)s
       THEN results_posted::real / applicable_completed END,
  avg_reporting_delay_days::real,
  now()
FROM per_sponsor
ON CONFLICT (sponsor) DO UPDATE SET
  sponsor_class = EXCLUDED.sponsor_class,
  total_studies = EXCLUDED.total_studies,
  applicable_completed = EXCLUDED.applicable_completed,
  results_posted = EXCLUDED.results_posted,
  missing_results = EXCLUDED.missing_results,
  compliance_rate = EXCLUDED.compliance_rate,
  avg_reporting_delay_days = EXCLUDED.avg_reporting_delay_days,
  updated_at = now()
"""


async def recompute_profiles() -> None:
    await execute(RECOMPUTE_PROFILES, {"min_trials": MIN_TRIALS_FOR_RATE})


async def profile_summary() -> dict:
    return await fetch_one(
        """
        SELECT count(*) AS sponsors,
               count(*) FILTER (WHERE compliance_rate IS NOT NULL) AS rated,
               round(avg(compliance_rate)::numeric, 2) AS avg_compliance_rate,
               sum(missing_results) AS missing_results
        FROM sponsor_profiles
        """
    )


async def get_profile(sponsor: str) -> dict | None:
    """Case-insensitive exact match on the sponsor name."""
    return await fetch_one(
        "SELECT * FROM sponsor_profiles WHERE lower(sponsor) = lower(%s)", (sponsor,)
    )


# Fixed ORDER BY fragments; callers pick one by key, so no input reaches the SQL text.
# Lowest compliance first, because the agents look for poor reporting.
SPONSOR_ORDER = {
    "compliance_rate": "compliance_rate ASC NULLS LAST, applicable_completed DESC",
    "missing_results": "missing_results DESC, sponsor",
    "total_studies": "total_studies DESC, sponsor",
}


async def list_profiles(
    condition_group: str | None, min_studies: int, order_by: str, limit: int
) -> list[dict]:
    return await fetch_all(
        f"""
        SELECT * FROM sponsor_profiles AS profile
        WHERE total_studies >= %(min_studies)s
          AND (%(condition_group)s::text IS NULL OR EXISTS (
                SELECT 1 FROM studies
                WHERE studies.sponsor = profile.sponsor
                  AND studies.condition_group = %(condition_group)s))
        ORDER BY {SPONSOR_ORDER[order_by]}
        LIMIT %(limit)s
        """,
        {"condition_group": condition_group, "min_studies": min_studies, "limit": limit},
    )


async def canonical_names(names: list[str]) -> dict[str, str]:
    """Lower-cased name -> the sponsor name as stored, for the names that exist."""
    rows = await fetch_all(
        "SELECT sponsor FROM sponsor_profiles WHERE lower(sponsor) = ANY(%s)",
        ([name.lower() for name in names],),
    )
    return {row["sponsor"].lower(): row["sponsor"] for row in rows}
