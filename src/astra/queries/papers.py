from astra.db import execute_many, fetch_one
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
