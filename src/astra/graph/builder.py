from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from astra.agents.registry import AGENTS
from astra.graph import nodes
from astra.graph.state import AstraState


def build_graph(store: BaseStore) -> CompiledStateGraph:
    """START -> guard_input -> supervisor -> specialists (parallel, via Send) -> validator
    -> hitl_gate -> write_brief -> finalize -> END. A blocked task skips straight to finalize."""
    graph = StateGraph(AstraState)
    graph.add_node("guard_input", nodes.guard_input)
    graph.add_node("supervisor", nodes.supervisor)
    for name, config in AGENTS.items():
        graph.add_node(name, nodes.make_specialist_node(config))
    graph.add_node("validator", nodes.validator)
    graph.add_node("hitl_gate", nodes.hitl_gate)
    graph.add_node("write_brief", nodes.write_brief)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges(
        "guard_input",
        lambda state: "finalize" if state["blocked"] else "supervisor",
        ["supervisor", "finalize"],
    )
    graph.add_conditional_edges("supervisor", nodes.dispatch, [*AGENTS, "finalize"])
    for name in AGENTS:
        graph.add_edge(name, "validator")
    graph.add_edge("validator", "hitl_gate")
    graph.add_edge("hitl_gate", "write_brief")
    graph.add_edge("write_brief", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(store=store, name="astra")
