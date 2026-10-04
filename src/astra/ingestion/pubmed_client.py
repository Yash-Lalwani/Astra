"""PubMed E-utilities client: esearch for PMIDs, efetch for article XML."""

import logging

import httpx
from langchain_core.rate_limiters import InMemoryRateLimiter
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from astra.config import settings
from astra.ingestion.parser import parse_pubmed_xml
from astra.models import ParsedPaper

logger = logging.getLogger(__name__)

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
REQUEST_TIMEOUT_SECONDS = 30
FETCH_BATCH_SIZE = 100

# NCBI allows 3 requests/s without an API key and 10/s with one.
_rate_limiter = InMemoryRateLimiter(requests_per_second=10 if settings.ncbi_api_key else 3)


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        # NCBI occasionally answers a valid request with a one-off 400 under load.
        return error.response.status_code in (400, 429) or error.response.status_code >= 500
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def _get(endpoint: str, params: dict[str, str | int]) -> httpx.Response:
    params = {**params, "tool": "astra"}
    if settings.ncbi_email:
        params["email"] = settings.ncbi_email
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    await _rate_limiter.aacquire()
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{BASE_URL}/{endpoint}", params=params)
    response.raise_for_status()
    return response


async def pmids_for_trial(nct_id: str, max_results: int = 20) -> list[str]:
    """Papers that list the trial in their secondary-source ID field."""
    response = await _get(
        "esearch.fcgi",
        {"db": "pubmed", "term": f"{nct_id}[si]", "retmax": max_results, "retmode": "json"},
    )
    return response.json().get("esearchresult", {}).get("idlist", [])


async def fetch_papers(pmids: list[str]) -> list[tuple[ParsedPaper, str]]:
    """Fetch and parse papers in batches; returns (paper, raw article XML) pairs."""
    papers: list[tuple[ParsedPaper, str]] = []
    for start in range(0, len(pmids), FETCH_BATCH_SIZE):
        batch = pmids[start : start + FETCH_BATCH_SIZE]
        response = await _get(
            "efetch.fcgi", {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"}
        )
        papers.extend(parse_pubmed_xml(response.text))
    logger.info("PubMed efetch: %d requested, %d parsed", len(pmids), len(papers))
    return papers
