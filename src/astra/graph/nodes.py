import json
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore
from langgraph.types import Send

from astra import llm
from astra.agents.react_agent import run_specialist
from astra.agents.registry import AgentConfig, load_prompt
from astra.agents.supervisor import route
from astra.graph import events
from astra.graph.state import AstraState, SpecialistInput
from astra.guardrails.input_checks import check_task
from astra.guardrails.validator import validate_signals
from astra.memory.episodic import save_episode
from astra.models import SavedSignal
from astra.queries import runs as run_queries
from astra.queries import signals as signal_queries
from astra.queries.guardrails import log_event

NCT_ID_PATTERN = re.compile(r"NCT\d{8}")
CLOSING_LINE = "*These signals are leads for human review, not conclusions of misconduct.*"


async def _block(run_id: str, reason: str) -> dict:
    await log_event(run_id, "input", "blocked", reason)
    events.emit("input_blocked", reason=reason)
    return {"blocked": True, "block_reason": reason}


async def guard_input(state: AstraState) -> dict:
    events.emit("run_started", task=state["task"])
    focus_nct_ids = sorted(set(NCT_ID_PATTERN.findall(state["task"].upper())))
    reason = check_task(state["task"])
    if reason:
        return {"focus_nct_ids": focus_nct_ids, **await _block(state["run_id"], reason)}
    return {"focus_nct_ids": focus_nct_ids, "blocked": False}


async def supervisor(state: AstraState) -> dict:
    decision, input_tokens, output_tokens = await route(state["task"], state["focus_nct_ids"])
    if not decision.in_scope:
        return await _block(state["run_id"], f"out of scope: {decision.reason}")
    # A condition group chosen when the run was created wins over the supervisor's guess.
    condition_group = state.get("condition_group") or decision.condition_group
    events.emit(
        "routing",
        agents=decision.agents,
        reason=decision.reason,
        condition_group=condition_group,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    await run_queries.save_routing(
        state["run_id"], decision.agents, decision.reason, condition_group
    )
    return {
        "selected_agents": decision.agents,
        "routing_reason": decision.reason,
        "condition_group": condition_group,
    }


def dispatch(state: AstraState) -> str | list[Send]:
    """Conditional edge after supervisor: run the chosen specialists in parallel."""
    if state.get("blocked"):
        return "finalize"
    payload = SpecialistInput(
        run_id=state["run_id"],
        task=state["task"],
        focus_nct_ids=state["focus_nct_ids"],
        condition_group=state.get("condition_group"),
    )
    return [Send(name, payload) for name in state["selected_agents"]]


def make_specialist_node(config: AgentConfig):
    async def specialist(payload: SpecialistInput, *, store: BaseStore) -> dict:
        events.emit("agent_started", agent=config.name)
        result = await run_specialist(
            config,
            payload["task"],
            run_id=payload["run_id"],
            focus_nct_ids=payload["focus_nct_ids"],
            condition_group=payload["condition_group"],
            store=store,
            on_tool_call=events.tool_call_emitter(config.name),
        )
        events.emit(
            "agent_finished",
            agent=config.name,
            signals=len(result.signals),
            steps=result.steps,
            tool_calls=result.tool_calls,
            tools_used=result.tools_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=result.duration_ms,
            error=result.error,
        )
        return {"agent_results": [result]}

    return specialist


async def validator(state: AstraState) -> dict:
    kept, dropped = await validate_signals(state["agent_results"], state["run_id"])
    events.emit("validation", kept=len(kept), dropped=len(dropped), capped=0, details=dropped)
    return {"validated_signals": kept}


async def hitl_gate(state: AstraState) -> dict:
    """Auto-approve confident findings; everything else waits in the review queue."""
    saved = [
        SavedSignal(
            **signal.model_dump(),
            signal_id=uuid.uuid4(),
            status="auto_approved"
            if signal.confidence >= signal.threshold and signal.citation_verified is not False
            else "pending_review",
        )
        for signal in state["validated_signals"]
    ]
    await signal_queries.insert_signals(state["run_id"], saved)
    pending = sum(signal.status == "pending_review" for signal in saved)
    await run_queries.save_counts(state["run_id"], len(saved), pending)
    events.emit("review_gate", auto_approved=len(saved) - pending, pending_review=pending)
    return {"saved_signals": saved}


async def write_brief(state: AstraState) -> dict:
    signals = state["saved_signals"]
    if not signals:
        brief = (
            f"## Summary\nNo signals were found for this task: {state['task']}\n\n{CLOSING_LINE}"
        )
        input_tokens = output_tokens = 0
    else:
        findings = [
            signal.model_dump(
                mode="json", include={"agent", "nct_id", "sponsor", "title", "summary",
                                      "confidence", "status", "evidence"}
            )
            for signal in signals
        ]  # fmt: skip
        message = f"Task: {state['task']}\n\nValidated signals:\n{json.dumps(findings)}"
        reply = await llm.plain_model("strong", temperature=0.3).ainvoke(
            [SystemMessage(load_prompt("brief.md")), HumanMessage(message)]
        )
        brief = reply.text
        input_tokens, output_tokens = llm.usage_of(reply)
    await run_queries.save_brief(state["run_id"], brief)
    events.emit("brief", markdown=brief, input_tokens=input_tokens, output_tokens=output_tokens)
    return {"brief": brief}


async def finalize(state: AstraState, *, store: BaseStore) -> dict:
    """Save one episode per agent that ran, so future runs can learn from this one."""
    if state.get("blocked"):
        return {}
    for result in state.get("agent_results", []):
        signals = [signal for signal in state["saved_signals"] if signal.agent == result.agent]
        await save_episode(store, state["run_id"], state["task"], result, signals)
    return {}
