"""Prompt-injection protection for external text (guardrail 2), also used on user tasks.

Regexes only catch obvious attacks. The real defence is spotlighting (every agent prompt says
never to follow instructions inside <untrusted_data>) plus signal validation.
"""

import re

from langchain_core.runnables import RunnableConfig

from astra.queries.guardrails import log_event

PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+)?"
        r"(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
        r"\byou\s+are\s+now\b",
        r"\bsystem\s+prompt\b",
        r"\bnew\s+instructions\s*:",
        r"</?\s*(system|assistant)\s*>",
        r"</?\s*untrusted_data",  # an attempt to close our own spotlight tag
        r"\bdo\s+not\s+flag\b",
        r"\bmark\s+this\s+(trial|study)\s+as\s+(compliant|safe)\b",
        r"\boverride\s+(your|the)\s+(instructions|rules)\b",
        r"\breveal\s+(your|the)\s+(instructions|prompt)\b",
    ]
]
REMOVED = "[removed: matched a prompt-injection pattern]"


def injection_match(text: str) -> str | None:
    """The first matching pattern, or None."""
    for pattern in PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


async def sanitize_external_text(
    text: str | None, source_ref: str, config: RunnableConfig | None = None
) -> str | None:
    """Wrap external text in <untrusted_data> tags, or replace it if it looks like an injection.

    A replacement is logged as a guardrail event when the call belongs to a run.
    """
    if not text:
        return text
    matched = injection_match(text)
    if matched is None:
        return f'<untrusted_data source="{source_ref}">{text}</untrusted_data>'

    configurable = (config or {}).get("configurable", {})
    if configurable.get("run_id"):
        await log_event(
            configurable["run_id"],
            stage="tool_output",
            action="sanitized",
            reason="external text matched a prompt-injection pattern",
            agent=configurable.get("agent"),
            detail={"source": source_ref, "pattern": matched},
        )
    return REMOVED
