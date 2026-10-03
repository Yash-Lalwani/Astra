import logging

from langchain_core.messages import HumanMessage, SystemMessage

from astra import llm
from astra.agents.registry import AGENTS, load_prompt
from astra.models import RoutingDecision

logger = logging.getLogger(__name__)

ALL_AGENTS = list(AGENTS)


def supervisor_prompt() -> str:
    agents = "\n".join(
        f"- `{config.name}` ({config.display_name}): {config.description}"
        for config in AGENTS.values()
    )
    return load_prompt("supervisor.md").replace("{agents}", agents)


async def route(task: str, focus_nct_ids: list[str]) -> tuple[RoutingDecision, int, int]:
    """Pick the specialists for a task. Returns (decision, input_tokens, output_tokens)."""
    message = f"Task: {task}\nTrials named in the task: {', '.join(focus_nct_ids) or 'none'}"
    try:
        output = await llm.structured_model("strong", RoutingDecision).ainvoke(
            [SystemMessage(supervisor_prompt()), HumanMessage(message)]
        )
        if output["parsed"] is None:
            raise ValueError(f"routing could not be parsed: {output['parsing_error']}")
    except Exception:
        logger.warning("Routing failed; running all agents", exc_info=True)
        fallback = RoutingDecision(
            in_scope=True,
            agents=ALL_AGENTS,
            condition_group=None,
            reason="routing failed: running all agents",
        )
        return fallback, 0, 0

    decision: RoutingDecision = output["parsed"]
    agents = list(dict.fromkeys(decision.agents))  # drop repeats, keep order
    if decision.in_scope and not agents:
        agents = ALL_AGENTS
    input_tokens, output_tokens = llm.usage_of(output["raw"])
    return decision.model_copy(update={"agents": agents}), input_tokens, output_tokens
