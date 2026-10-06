"""Load paper abstracts and trial texts into Layer-Engine for search_evidence and citation checks.

Run with `python -m astra.ingestion --to-layer`; it also runs at the end of a normal ingestion when
Layer is enabled. Rows already sent (layer_ingested_at set) are skipped.
"""

import base64
import logging

from langchain_core.rate_limiters import InMemoryRateLimiter

from astra.config import settings
from astra.models import ParsedStudy
from astra.queries import papers as paper_queries
from astra.queries import trials as trial_queries
from astra.tools import evidence_tools

logger = logging.getLogger(__name__)

# Search settings for Astra's collection: no LLM grading or web fallback (agents judge relevance
# themselves, and every search stays free of LLM tokens), strict citation checks.
COLLECTION_SETTINGS = {
    "search_mode": "hybrid",
    "top_k": 5,
    "fetch_k": 20,
    "rerank": True,
    "reranker": "local",
    "hyde": False,
    "crag": False,
    "crag_web_fallback": False,
    "self_rag": False,
    "citation_mode": "strict",
    "domain_description": (
        "ClinicalTrials.gov registry records and PubMed abstracts of clinical trials "
        "(oncology, cardiovascular, CNS/mental health, type 2 diabetes)"
    ),
    "filterable_fields": ["source_type", "nct_ids", "pmid", "condition_group"],
}
# Layer allows 100 calls per minute per key.
_rate_limiter = InMemoryRateLimiter(requests_per_second=1.5)


def paper_document(paper: dict) -> tuple[str, str, dict]:
    """(doc_id, markdown, metadata) for one paper."""
    markdown = (
        f"# {paper['title']}\n"
        f"PMID: {paper['pmid']} | Journal: {paper['journal'] or 'unknown'} | "
        f"Published: {paper['pub_date'] or 'unknown'} | "
        f"Linked trials: {', '.join(paper['nct_ids'])}\n"
        f"## Abstract\n{paper['abstract'] or '(no abstract)'}\n"
    )
    metadata = {
        "source_type": "paper",
        "pmid": paper["pmid"],
        "nct_ids": paper["nct_ids"],
        "condition_group": paper["condition_groups"],
    }
    return f"pmid_{paper['pmid']}", markdown, metadata


def _adverse_event_text(study: ParsedStudy) -> str:
    events = study.adverse_events
    if events is None:
        return "No adverse event results posted."
    terms = ", ".join(f"{t.term} ({t.affected})" for t in events.top_serious_terms) or "none"
    deaths = "not reported" if events.total_deaths is None else events.total_deaths
    return (
        f"{events.total_serious_affected} of {events.total_at_risk} participants had a serious "
        f"adverse event; deaths: {deaths}. Most frequent serious events: {terms}."
    )


def trial_document(study: ParsedStudy) -> tuple[str, str, dict]:
    """(doc_id, markdown, metadata) for one trial's registry text."""
    registered = "\n".join(
        f"- {outcome.measure} (time frame: {outcome.time_frame or 'not given'})"
        for outcome in study.registered_primary_outcomes
    )
    reported = "\n".join(
        f"- {outcome.title} (time frame: {outcome.time_frame or 'not given'})"
        for outcome in study.reported_primary_outcomes
    )
    markdown = (
        f"# {study.title}\n"
        f"NCT ID: {study.nct_id} | Sponsor: {study.sponsor} | Status: {study.overall_status}\n"
        f"## Brief summary\n{study.brief_summary or '(none)'}\n"
        f"## Detailed description\n{study.detailed_description or '(none)'}\n"
        f"## Registered primary outcomes\n{registered or '(none)'}\n"
        f"## Reported primary outcomes\n{reported or '(no results posted)'}\n"
        f"## Serious adverse events\n{_adverse_event_text(study)}\n"
    )
    metadata = {
        "source_type": "registry",
        "nct_ids": [study.nct_id],
        "condition_group": [study.condition_group],
    }
    return f"nct_{study.nct_id}", markdown, metadata


async def ensure_collection() -> None:
    collections = await evidence_tools.call_layer("list_collections")
    # Layer returns a single object when only one collection exists.
    if isinstance(collections, dict):
        collections = [collections]
    if any(collection["id"] == settings.layer_collection for collection in collections):
        return
    await evidence_tools.call_layer(
        "create_collection",
        collection_id=settings.layer_collection,
        name="Astra clinical trials",
        description="Trial registry texts and linked PubMed abstracts for Astra's agents.",
        settings=COLLECTION_SETTINGS,
    )
    logger.info("Created Layer collection %s", settings.layer_collection)


async def _ingest(doc_id: str, markdown: str, metadata: dict) -> str:
    await _rate_limiter.aacquire()
    result = await evidence_tools.call_layer(
        "ingest_document",
        collection_id=settings.layer_collection,
        content_base64=base64.b64encode(markdown.encode()).decode(),
        filename=f"{doc_id}.md",
        doc_id=doc_id,
        metadata=metadata,
    )
    return result.get("status", "ok")


async def ingest_to_layer(limit: int | None = None) -> dict[str, int]:
    """Send every paper and trial not yet in Layer (at most `limit` of each); returns counts."""
    await ensure_collection()
    counts = {"papers": 0, "trials": 0, "failed": 0}
    papers = (await paper_queries.papers_for_layer())[:limit]
    studies = (await trial_queries.studies_for_layer())[:limit]
    jobs = [(paper_document(p), paper_queries.mark_in_layer, p["pmid"], "papers") for p in papers]
    jobs += [(trial_document(s), trial_queries.mark_in_layer, s.nct_id, "trials") for s in studies]
    for (doc_id, markdown, metadata), mark_done, key, kind in jobs:
        try:
            await _ingest(doc_id, markdown, metadata)
        except Exception:
            logger.warning("Layer ingest of %s failed; it will be retried next time", doc_id,
                           exc_info=True)  # fmt: skip
            counts["failed"] += 1
            continue
        await mark_done(key)
        counts[kind] += 1
    logger.info("Layer ingest: %s", counts)
    return counts
