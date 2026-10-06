"""Layer-Engine (RAG over MCP): the search_evidence agent tool, and verify_claim for the validator.

Astra is an MCP client of Layer-Engine. Its tools are loaded once and called by name; these
wrappers keep the agents' interface stable and sanitize every passage before a model sees it.
"""

import json
import re
from datetime import timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from astra.config import settings
from astra.guardrails.injection import sanitize_external_text
from astra.tools.trial_tools import check_choice, check_nct_id, clip, to_json

SOURCE_TYPES = {"paper", "registry"}
MAX_EVIDENCE_K = 10
# The first call after Layer has been idle takes about 20 s while the server wakes up.
LAYER_TIMEOUT = timedelta(seconds=90)

_layer_tools: dict[str, BaseTool] | None = None


class LayerError(Exception):
    """A tool error returned by Layer-Engine (e.g. "Unauthorized: ...", "Blocked: ...")."""


async def _tools() -> dict[str, BaseTool]:
    global _layer_tools
    if _layer_tools is None:
        client = MultiServerMCPClient(
            {
                "layer": {
                    "transport": "streamable_http",
                    "url": settings.layer_mcp_url,
                    "headers": {"Authorization": f"Bearer {settings.layer_api_key}"},
                    "timeout": LAYER_TIMEOUT,
                    "sse_read_timeout": LAYER_TIMEOUT,
                }
            }
        )
        _layer_tools = {layer_tool.name: layer_tool for layer_tool in await client.get_tools()}
    return _layer_tools


async def call_layer(tool_name: str, /, **args: Any) -> Any:
    """Call one Layer-Engine tool and return its JSON result. tool_name is positional-only
    because some Layer tools have an argument called `name`."""
    result = await (await _tools())[tool_name].ainvoke(args)
    text = result[0]["text"] if isinstance(result, list) else str(result)
    if text.startswith("Error executing tool"):
        raise LayerError(text)
    return json.loads(text)


def _chunks(result: dict) -> list[dict]:
    """Layer's search returns {"chunks": [{id, text, rerank_score, metadata, ...}]}."""
    return result.get("chunks", [])


@tool
async def search_evidence(
    query: str,
    config: RunnableConfig,
    nct_id: str | None = None,
    source_type: str | None = None,
    k: int = 5,
) -> str:
    """Search the full text of linked papers (abstracts) and registry records by meaning and
    keywords. nct_id restricts the search to that trial's documents; source_type is 'paper'
    or 'registry'. Returns passages with their score, source_type, pmid and nct_ids."""
    filters: dict[str, str] = {}
    if nct_id:
        filters["nct_ids"] = check_nct_id(nct_id)
    if source_type:
        filters["source_type"] = check_choice("source_type", source_type.lower(), SOURCE_TYPES)
    if not 1 <= k <= MAX_EVIDENCE_K:
        raise ValueError(f"k must be between 1 and {MAX_EVIDENCE_K}")

    result = await call_layer(
        "search",
        collection_id=settings.layer_collection,
        query=query,
        top_k=k,
        filters=filters or None,
    )
    passages = []
    for chunk in _chunks(result):
        metadata = chunk.get("metadata", {})
        source = (
            f"PMID:{metadata['pmid']}"
            if metadata.get("pmid")
            else ",".join(metadata.get("nct_ids", []))
        )
        passages.append(
            {
                "text": await sanitize_external_text(clip(chunk.get("text")), source, config),
                "score": round(chunk.get("rerank_score") or 0.0, 2),
                "source_type": metadata.get("source_type"),
                "pmid": metadata.get("pmid"),
                "nct_ids": metadata.get("nct_ids", []),
            }
        )
    return to_json({"query": query, "count": len(passages), "passages": passages})


def pmid_from_reference(reference: str) -> str:
    """'PMID 123', 'PMID:123' or '123' -> '123' (synthetic IDs such as SYNTH-0001 pass through)."""
    return re.sub(r"(?i)^\s*pmid[:\s]*", "", reference).strip()


async def verify_claim(claim: str, pmid: str) -> bool | None:
    """Whether the paper's text supports the claim (Layer's strict citation check).
    None when the paper has no passages in Layer, so nothing could be checked."""
    result = await call_layer(
        "search",
        collection_id=settings.layer_collection,
        query=claim,
        top_k=5,
        filters={"pmid": pmid},
    )
    passages = [{"id": chunk["id"], "text": chunk["text"]} for chunk in _chunks(result)]
    if not passages:
        return None
    verdict = await call_layer(
        "verify_citations",
        statements=[{"text": claim, "chunk_ids": [passage["id"] for passage in passages]}],
        passages=passages,
        strict=True,
    )
    return bool(verdict.get("all_supported"))


async def layer_healthy() -> bool:
    try:
        return (await call_layer("health")).get("status") == "ok"
    except Exception:
        return False
