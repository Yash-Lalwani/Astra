"""ClinicalTrials.gov v2 client.

Uses `requests` (via asyncio.to_thread) with a browser User-Agent because CT.gov's bot
protection returns 403 to httpx.
"""

import asyncio
import logging
from functools import cache
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

BASE_URL = "https://clinicaltrials.gov/api/v2"
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 30
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


@cache
def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
    reraise=True,
)
def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = _session().get(f"{BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


async def search_studies(
    condition: str,
    statuses: list[str],
    advanced_filter: str | None = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Raw study JSONs matching a condition query, following nextPageToken pagination."""
    params: dict[str, Any] = {
        "query.cond": condition,
        "filter.overallStatus": "|".join(statuses),  # v2 wants "|", not ","
        "pageSize": min(PAGE_SIZE, max_results),
        "format": "json",
    }
    if advanced_filter:
        params["filter.advanced"] = advanced_filter

    studies: list[dict[str, Any]] = []
    while len(studies) < max_results:
        page = await asyncio.to_thread(_get_json, "/studies", params)
        studies.extend(page.get("studies", []))
        next_token = page.get("nextPageToken")
        if not next_token:
            break
        params["pageToken"] = next_token
    logger.info("CT.gov search %r %s -> %d studies", condition, statuses, len(studies))
    return studies[:max_results]
