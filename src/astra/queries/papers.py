from astra.db import execute, execute_many, fetch_all, fetch_one
from astra.models import ParsedPaper

UPSERT_PAPER = """
INSERT INTO papers (pmid, title, abstract, journal, pub_date)
VALUES (%(pmid)s, %(title)s, %(abstract)s, %(journal)s, %(pub_date)s)
ON CONFLICT (pmid) DO UPDATE SET
  title = EXCLUDED.title,
  abstract = EXCLUDED.abstract,
  journal = EXCLUDED.journal,
  pub_date = EXCLUDED.pub_date,
  ingested_at = now()
"""

LINK_STUDY_PAPER = """
INSERT INTO study_papers (nct_id, pmid, link_source)
VALUES (%s, %s, %s)
ON CONFLICT (nct_id, pmid) DO NOTHING
"""


async def upsert_papers(papers: list[ParsedPaper]) -> None:
    await execute_many(UPSERT_PAPER, [paper.model_dump() for paper in papers])


async def link_papers(links: list[tuple[str, str, str]]) -> None:
    """links: (nct_id, pmid, link_source) where link_source is registry_reference | pubmed_si."""
    await execute_many(LINK_STUDY_PAPER, links)


async def paper_counts() -> dict:
    return await fetch_one(
        """
        SELECT (SELECT count(*) FROM papers) AS papers,
               (SELECT count(*) FROM study_papers) AS links,
               (SELECT count(DISTINCT nct_id) FROM study_papers) AS trials_with_papers
        """
    )


async def linked_papers(nct_id: str, limit: int) -> list[dict]:
    return await fetch_all(
        """
        SELECT papers.pmid, papers.title, papers.journal, papers.pub_date, papers.abstract,
               papers.is_synthetic, study_papers.link_source
        FROM study_papers
        JOIN papers USING (pmid)
        WHERE study_papers.nct_id = %s
        ORDER BY papers.pub_date DESC NULLS LAST, papers.pmid
        LIMIT %s
        """,
        (nct_id, limit),
    )


async def papers_for_layer() -> list[dict]:
    """Papers not yet in Layer-Engine, with their linked trials and condition groups."""
    return await fetch_all(
        """
        SELECT papers.pmid, papers.title, papers.abstract, papers.journal, papers.pub_date,
               array_agg(DISTINCT study_papers.nct_id) AS nct_ids,
               array_agg(DISTINCT studies.condition_group) AS condition_groups
        FROM papers
        JOIN study_papers USING (pmid)
        JOIN studies ON studies.nct_id = study_papers.nct_id
        WHERE papers.layer_ingested_at IS NULL
        GROUP BY papers.pmid
        ORDER BY papers.pmid
        """
    )


async def mark_in_layer(pmid: str) -> None:
    await execute("UPDATE papers SET layer_ingested_at = now() WHERE pmid = %s", (pmid,))


async def upsert_synthetic_papers(papers: list[ParsedPaper]) -> None:
    """Guardrail demo papers: stored like real ones but flagged is_synthetic."""
    await execute_many(
        """
        INSERT INTO papers (pmid, title, abstract, journal, pub_date, is_synthetic)
        VALUES (%(pmid)s, %(title)s, %(abstract)s, %(journal)s, %(pub_date)s, TRUE)
        ON CONFLICT (pmid) DO UPDATE SET
          title = EXCLUDED.title,
          abstract = EXCLUDED.abstract,
          is_synthetic = TRUE,
          layer_ingested_at = NULL
        """,
        [paper.model_dump() for paper in papers],
    )
