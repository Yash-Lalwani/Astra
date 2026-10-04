"""Scripted stand-ins for the LLM factories in astra.llm, shared by the graph and API tests."""

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from astra import llm
from astra.agents.react_agent import react_agent_for
from astra.agents.registry import AGENTS
from astra.models import AgentFindings, EvidenceItem, RoutingDecision, SignalDraft

USAGE = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
CONFIDENCE = {"missing_results": 0.9, "timeline": 0.5}  # threshold 0.65 and 0.6


def ai(text: str = "", tool_calls: list | None = None) -> AIMessage:
    return AIMessage(text, tool_calls=tool_calls or [], usage_metadata=USAGE)


def agent_of(messages) -> str:
    """Which specialist is calling, read from the header of its system prompt."""
    header = messages[0].content.splitlines()[0].removeprefix("# ")
    return next(name for name, config in AGENTS.items() if config.display_name == header)


class FakeModels:
    def __init__(self, route: RoutingDecision, failing_agent: str | None = None):
        self.route = route
        self.failing_agent = failing_agent
        self.route_calls = 0

    def tool_model(self, role, tools):
        def reply(messages):
            if agent_of(messages) == self.failing_agent:
                raise RuntimeError("provider error")
            if any(isinstance(message, ToolMessage) for message in messages):
                return ai("done")
            return ai(tool_calls=[{"name": tools[0].name, "args": {}, "id": "call-1"}])

        return RunnableLambda(reply)

    def structured_model(self, role, schema):
        def reply(messages):
            if schema is RoutingDecision:
                self.route_calls += 1
                parsed = self.route
            else:
                agent = agent_of(messages)
                evidence = [EvidenceItem(source="registry", reference="NCT00000001", detail="d")]
                signal = SignalDraft(
                    nct_id="NCT00000001",
                    title=f"{agent} finding",
                    summary="s",
                    evidence=evidence,
                    confidence=CONFIDENCE[agent],
                )
                parsed = AgentFindings(signals=[signal], notes=f"{agent} notes")
            return {"raw": ai("{}"), "parsed": parsed, "parsing_error": None}

        return RunnableLambda(reply)

    def plain_model(self, role, temperature=0.0):
        return RunnableLambda(lambda messages: ai("## Summary\nTwo findings."))


def use_fakes(monkeypatch, fakes: FakeModels) -> None:
    for name in ("tool_model", "structured_model", "plain_model"):
        monkeypatch.setattr(llm, name, getattr(fakes, name))
    react_agent_for.cache_clear()  # subgraphs must be rebuilt with the fake models


def route_to(*agents: str) -> RoutingDecision:
    return RoutingDecision(in_scope=True, agents=list(agents), condition_group=None, reason="r")
