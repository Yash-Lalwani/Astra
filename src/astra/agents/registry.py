from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langchain_core.tools import BaseTool

from astra.config import settings
from astra.models import AgentName
from astra.tools.evidence_tools import search_evidence
from astra.tools.pubmed_tools import get_linked_papers
from astra.tools.trial_tools import (
    compare_outcomes,
    cross_study_stats,
    find_missing_results,
    find_timeline_issues,
    get_adverse_event_summary,
    get_sponsor_profile,
    get_trial,
    list_sponsors,
    search_trials,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class AgentConfig:
    name: AgentName
    display_name: str
    description: str
    signal_type: str
    level: Literal["trial", "sponsor", "aggregate"]
    threshold: float
    tools: tuple[BaseTool, ...]
    prompt_file: str


def load_prompt(file_name: str) -> str:
    return (PROMPTS_DIR / file_name).read_text(encoding="utf-8")


# These agents also get search_evidence (Layer-Engine), but only while Layer is enabled.
EVIDENCE_AGENTS = {"broken_promises", "side_effect"}


def agent_tools(config: "AgentConfig") -> tuple[BaseTool, ...]:
    if config.name in EVIDENCE_AGENTS and settings.layer_enabled:
        return (*config.tools, search_evidence)
    return config.tools


AGENTS: dict[str, AgentConfig] = {
    config.name: config
    for config in [
        AgentConfig(
            name="missing_results",
            display_name="Missing Results",
            description="Finds completed trials whose legally required results are overdue.",
            signal_type="missing_results",
            level="trial",
            threshold=0.65,
            tools=(find_missing_results, get_trial, get_sponsor_profile),
            prompt_file="missing_results.md",
        ),
        AgentConfig(
            name="broken_promises",
            display_name="Broken Promises",
            description=(
                "Checks whether the registered primary outcome matches what was reported in "
                "results and linked papers (outcome switching)."
            ),
            signal_type="broken_promise",
            level="trial",
            threshold=0.60,
            tools=(search_trials, compare_outcomes, get_trial, get_linked_papers),
            prompt_file="broken_promises.md",
        ),
        AgentConfig(
            name="track_record",
            display_name="Track Record",
            description="Rates sponsors by how reliably they post due results (compliance rate).",
            signal_type="low_credibility",
            level="sponsor",
            threshold=0.70,
            tools=(list_sponsors, get_sponsor_profile, search_trials),
            prompt_file="track_record.md",
        ),
        AgentConfig(
            name="pattern_finder",
            display_name="Pattern Finder",
            description=(
                "Compares sponsors or condition groups to find outliers, such as a sponsor whose "
                "missing-results rate is far above its peers."
            ),
            signal_type="cross_study",
            level="aggregate",
            threshold=0.65,
            tools=(cross_study_stats, list_sponsors, search_trials),
            prompt_file="pattern_finder.md",
        ),
        AgentConfig(
            name="side_effect",
            display_name="Side Effect Checker",
            description=(
                "Finds serious adverse events posted in the registry that linked papers do not "
                "mention."
            ),
            signal_type="safety_gap",
            level="trial",
            threshold=0.55,
            tools=(search_trials, get_adverse_event_summary, get_linked_papers),
            prompt_file="side_effect.md",
        ),
        AgentConfig(
            name="timeline",
            display_name="Timeline Analyst",
            description=(
                "Finds trials silently past their own schedule: still active long after the "
                "estimated completion date, or not updated for years."
            ),
            signal_type="timeline_delay",
            level="trial",
            threshold=0.60,
            tools=(find_timeline_issues, get_trial, get_sponsor_profile),
            prompt_file="timeline.md",
        ),
    ]
}
