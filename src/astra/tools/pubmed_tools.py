from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from astra.guardrails.injection import sanitize_external_text
from astra.queries import papers as paper_queries
from astra.tools.trial_tools import check_limit, check_nct_id, clip, to_json


@tool
async def get_linked_papers(nct_id: str, config: RunnableConfig, limit: int = 5) -> str:
    """Papers linked to a trial (from the registry's references or PubMed's NCT ID field),
    newest first: pmid, title, journal, pub_date, abstract, and is_synthetic (true only for
    guardrail demo papers)."""
    nct_id = check_nct_id(nct_id)
    papers = await paper_queries.linked_papers(nct_id, check_limit(limit))
    for paper in papers:
        paper["abstract"] = await sanitize_external_text(
            clip(paper["abstract"]), f"PMID:{paper['pmid']}", config
        )
    return to_json({"nct_id": nct_id, "count": len(papers), "papers": papers})
