"""The one hand-built ReAct subgraph every specialist uses, and run_specialist() to run it.

    START -> agent --(tool calls and steps < AGENT_MAX_STEPS)--> tools -> agent
               \\--(otherwise)--> report -> END

No streaming code lives here: live tool events leave through the on_tool_call callback.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from functools import cache
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from astra import llm
from astra.agents.registry import AGENTS, AgentConfig, load_prompt
from astra.config import settings
from astra.memory.procedural import DEFAULT_RULES
from astra.models import AgentFindings, AgentResult
from astra.queries.guardrails import log_event

logger = logging.getLogger(__name__)

REPORT_INSTRUCTION = (
    "Now report your findings. Use only facts that appear in the tool results above and cite "
    "each one in `evidence` (NCT ID, PMID, or sponsor:<name> / group:<value>). "
    "Write each title yourself as a short description of the finding, not a trial or paper "
    "title. Return an empty signals list if nothing qualifies."
)


class ReactState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int
    findings: AgentFindings | None


def build_react_agent(config: AgentConfig) -> CompiledStateGraph:
    model = llm.tool_model("fast", config.tools)
    reporter = llm.structured_model("fast", AgentFindings)

    async def agent(state: ReactState) -> dict:
        reply = await model.ainvoke(state["messages"])
        return {"messages": [reply], "steps": state["steps"] + 1}

    def after_agent(state: ReactState) -> str:
        if state["messages"][-1].tool_calls and state["steps"] < settings.agent_max_steps:
            return "tools"
        return "report"

    async def report(state: ReactState) -> dict:
        messages = state["messages"]
        # Step cap hit mid-loop: providers reject a request that ends in unanswered tool calls.
        if messages[-1].tool_calls:
            messages = messages[:-1]
        output = await reporter.ainvoke([*messages, HumanMessage(REPORT_INSTRUCTION)])
        if output["parsed"] is None:
            raise ValueError(f"findings could not be parsed: {output['parsing_error']}")
        # The raw message is kept in the conversation so its token usage is counted.
        return {"messages": [output["raw"]], "findings": output["parsed"]}

    graph = StateGraph(ReactState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(list(config.tools), handle_tool_errors=True))
    graph.add_node("report", report)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", "report"])
    graph.add_edge("tools", "agent")
    graph.add_edge("report", END)
    return graph.compile(name=config.name)


@cache
def react_agent_for(name: str) -> CompiledStateGraph:
    """Each specialist's subgraph is compiled once and reused."""
    return build_react_agent(AGENTS[name])


def build_system_prompt(config: AgentConfig) -> str:
    rules = "\n".join(f"- {rule}" for rule in DEFAULT_RULES[config.name])
    return f"{load_prompt(config.prompt_file)}\n\n## Rules from reviewer feedback\n{rules}"


def build_task_message(task: str, focus_nct_ids: list[str], condition_group: str | None) -> str:
    return (
        f"Task: {task}\n"
        f"Focus trials: {', '.join(focus_nct_ids) or 'none'}\n"
        f"Condition group: {condition_group or 'any'}"
    )


async def _stream_agent(
    config: AgentConfig,
    messages: list[AnyMessage],
    run_id: str | None,
    on_tool_call: Callable[[str, dict], None] | None,
) -> dict:
    """Run the subgraph, reporting each tool call that will execute; returns the final state."""
    final_state: dict = {}
    async for mode, chunk in react_agent_for(config.name).astream(
        {"messages": messages, "steps": 0, "findings": None},
        config={
            "recursion_limit": 2 * settings.agent_max_steps + 5,
            "run_name": config.name,
            "tags": ["specialist", config.name],
            "metadata": {"run_id": run_id, "agent": config.name},
            "configurable": {"run_id": run_id, "agent": config.name},
        },
        stream_mode=["updates", "values"],
    ):
        if mode == "values":
            final_state = chunk
        elif on_tool_call and "agent" in chunk:
            update = chunk["agent"]
            # Tool calls made on the last allowed step go to report, not to the tools.
            if update["steps"] < settings.agent_max_steps:
                for call in update["messages"][-1].tool_calls:
                    on_tool_call(call["name"], call["args"])
    return final_state


def _result(config: AgentConfig, state: dict, duration_ms: int) -> AgentResult:
    messages = state["messages"]
    usages = [llm.usage_of(message) for message in messages if isinstance(message, AIMessage)]
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
    return AgentResult(
        agent=config.name,
        signals=state["findings"].signals,
        notes=state["findings"].notes,
        steps=state["steps"],
        tool_calls=len(tool_messages),
        tools_used=sorted({message.name for message in tool_messages}),
        input_tokens=sum(input_tokens for input_tokens, _ in usages),
        output_tokens=sum(output_tokens for _, output_tokens in usages),
        duration_ms=duration_ms,
    )


async def run_specialist(
    config: AgentConfig,
    task: str,
    *,
    run_id: str | None,
    focus_nct_ids: list[str],
    condition_group: str | None,
    on_tool_call: Callable[[str, dict], None] | None = None,
) -> AgentResult:
    """Run one specialist end to end. Never raises: failures come back as AgentResult.error."""
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    messages = [
        SystemMessage(build_system_prompt(config)),
        HumanMessage(build_task_message(task, focus_nct_ids, condition_group)),
    ]
    try:
        state = await asyncio.wait_for(
            _stream_agent(config, messages, run_id, on_tool_call), settings.agent_timeout_seconds
        )
    except TimeoutError:
        reason = f"stopped after {settings.agent_timeout_seconds}s"
        logger.warning("Agent %s %s", config.name, reason)
        if run_id:
            await log_event(run_id, "usage_limit", "stopped", reason, agent=config.name)
        return AgentResult(agent=config.name, error=reason, duration_ms=elapsed_ms())
    except Exception as error:
        logger.exception("Agent %s failed", config.name)
        error_text = f"{type(error).__name__}: {error}"
        return AgentResult(agent=config.name, error=error_text, duration_ms=elapsed_ms())
    return _result(config, state, elapsed_ms())
