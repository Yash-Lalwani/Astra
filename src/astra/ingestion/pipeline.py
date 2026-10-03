import logging
from datetime import date

from astra.config import CONDITION_GROUPS
from astra.db import apply_schema
from astra.ingestion import clinical_trials_client, gcs_store, pubmed_client
from astra.ingestion.parser import parse_study
from astra.memory.semantic import compute_sponsor_profiles
from astra.models import ParsedStudy
from astra.queries import papers as paper_queries
from astra.queries import trials as trial_queries

logger = logging.getLogger(__name__)

EARLIEST_PRIMARY_COMPLETION = "2012-01-01"
MONTHS_FOR_RESULTS_TO_BE_DUE = 18
# ~70% finished trials (results can be due), ~30% still "active" (timeline delays).
STATUS_MIX: list[tuple[list[str], float]] = [
    (["COMPLETED", "TERMINATED"], 0.7),
    (["RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "UNKNOWN"], 0.3),
]


def months_ago(today: date, months: int) -> date:
    year, month_index = divmod(today.year * 12 + today.month - 1 - months, 12)
    return date(year, month_index + 1, min(today.day, 28))


def selection_filter(today: date) -> str:
    """CT.gov Essie filter: interventional, FDA regulated, primary completion between 2012 and
    18 months ago. Without the FDA flag a trial can never count as applicable (rules.py)."""
    latest = months_ago(today, MONTHS_FOR_RESULTS_TO_BE_DUE).isoformat()
    return (
        "AREA[StudyType]INTERVENTIONAL AND "
        f"AREA[PrimaryCompletionDate]RANGE[{EARLIEST_PRIMARY_COMPLETION}, {latest}] AND "
        "(AREA[IsFDARegulatedDrug]true OR AREA[IsFDARegulatedDevice]true)"
    )


async def select_group_studies(
    group: str, per_condition: int, taken: set[str], today: date
) -> list[ParsedStudy]:
    """Fetch, store raw, and parse one condition group's studies.

    A trial can match two groups' queries; the first group keeps it (`taken`), so the
    stored condition_group is deterministic across re-runs.
    """
    selected: list[ParsedStudy] = []
    for statuses, share in STATUS_MIX:
        target = round(per_condition * share)
        # Ask for extra so trials already taken by an earlier group can be skipped.
        raw_studies = await clinical_trials_client.search_studies(
            CONDITION_GROUPS[group], statuses, selection_filter(today), max_results=target * 2
        )
        added = 0
        for raw in raw_studies:
            nct_id = raw["protocolSection"]["identificationModule"]["nctId"]
            if nct_id in taken:
                continue
            await gcs_store.save_json(gcs_store.raw_study_path(nct_id), raw)
            try:
                study = parse_study(raw, group)
            except Exception:
                logger.exception("Could not parse %s; skipping it", nct_id)
                continue
            await gcs_store.save_json(
                gcs_store.processed_study_path(nct_id), study.model_dump(mode="json")
            )
            taken.add(nct_id)
            selected.append(study)
            added += 1
            if added == target:
                break
        if added < target:
            logger.warning("%s %s: only %d of %d trials found", group, statuses, added, target)
    return selected


async def ingest_papers(studies: list[ParsedStudy]) -> None:
    """Registry RESULT/DERIVED references plus a PubMed [si] search for every trial."""
    link_sources: dict[tuple[str, str], str] = {}
    for study in studies:
        for pmid in study.reference_pmids:
            link_sources[(study.nct_id, pmid)] = "registry_reference"
        for pmid in await pubmed_client.pmids_for_trial(study.nct_id):
            link_sources.setdefault((study.nct_id, pmid), "pubmed_si")

    pmids = sorted({pmid for _, pmid in link_sources})
    fetched = await pubmed_client.fetch_papers(pmids)
    for paper, raw_xml in fetched:
        await gcs_store.save_text(gcs_store.raw_paper_path(paper.pmid), raw_xml, "application/xml")
        await gcs_store.save_json(
            gcs_store.processed_paper_path(paper.pmid), paper.model_dump(mode="json")
        )
    await paper_queries.upsert_papers([paper for paper, _ in fetched])

    # Only link papers PubMed actually returned, so the foreign key always holds.
    fetched_pmids = {paper.pmid for paper, _ in fetched}
    links = [
        (nct_id, pmid, source)
        for (nct_id, pmid), source in sorted(link_sources.items())
        if pmid in fetched_pmids
    ]
    await paper_queries.link_papers(links)
    logger.info("Papers: %d fetched, %d trial links", len(fetched), len(links))


async def run_ingestion(per_condition: int, groups: list[str], today: date | None = None) -> None:
    today = today or date.today()
    await apply_schema()
    taken: set[str] = set()
    studies: list[ParsedStudy] = []
    for group in groups:
        group_studies = await select_group_studies(group, per_condition, taken, today)
        logger.info("%s: %d trials selected", group, len(group_studies))
        studies.extend(group_studies)

    await trial_queries.upsert_studies(studies)
    await ingest_papers(studies)
    await compute_sponsor_profiles()
    logger.info("Ingestion finished: %d trials", len(studies))
