import operator
from typing import Annotated, TypedDict

from astra.models import AgentResult, SavedSignal, ValidatedSignal


class AstraState(TypedDict, total=False):
    run_id: str
    task: str
    focus_nct_ids: list[str]
    blocked: bool
    block_reason: str | None
    selected_agents: list[str]
    routing_reason: str
    condition_group: str | None
    # Specialists run in parallel; each appends exactly one result.
    agent_results: Annotated[list[AgentResult], operator.add]
    validated_signals: list[ValidatedSignal]
    saved_signals: list[SavedSignal]
    brief: str


class SpecialistInput(TypedDict):
    """The payload Send() gives each specialist node."""

    run_id: str
    task: str
    focus_nct_ids: list[str]
    condition_group: str | None
