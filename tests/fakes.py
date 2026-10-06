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


class FakeLayer:
    """Stands in for evidence_tools.call_layer: records each call and returns canned replies."""

    def __init__(self, chunks: list[dict] | None = None, supported: bool = True):
        self.calls: list[tuple[str, dict]] = []
        self.chunks = chunks or []
        self.supported = supported
        self.collections: list[dict] = [{"id": "k8s-demo"}]

    async def __call__(self, name: str, /, **args):
        self.calls.append((name, args))
        if name == "search":
            return {"chunks": self.chunks}
        if name == "verify_citations":
            return {"all_supported": self.supported}
        if name == "list_collections":
            return self.collections[0] if len(self.collections) == 1 else self.collections
        if name == "create_collection":
            self.collections.append({"id": args["collection_id"]})
            return {"id": args["collection_id"]}
        if name == "ingest_document":
            return {"status": "created"}
        if name == "health":
            return {"status": "ok"}
        raise AssertionError(f"unexpected Layer call {name}")

    def called(self, name: str) -> list[dict]:
        return [args for called_name, args in self.calls if called_name == name]


def enable_layer(monkeypatch, layer: FakeLayer) -> None:
    from astra.config import settings
    from astra.tools import evidence_tools

    monkeypatch.setattr(settings, "layer_mcp_url", "https://layer.test/mcp")
    monkeypatch.setattr(evidence_tools, "call_layer", layer)
