from astra.db import execute, fetch_one

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
