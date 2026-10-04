"""Live run events: the only streaming code in Astra. Graph nodes call these helpers; agents,
tools and memory never do. Outside a streamed run the writer does nothing."""

from collections.abc import Callable
from typing import Any

from langgraph.config import get_stream_writer

MAX_ARG_CHARS = 100


def emit(event_type: str, **fields: Any) -> None:
    get_stream_writer()({"type": event_type, **fields})


def _short(value: Any) -> Any:
    text = str(value)
    return value if len(text) <= MAX_ARG_CHARS else text[:MAX_ARG_CHARS] + "..."


def tool_call_emitter(agent: str) -> Callable[[str, dict], None]:
    """The on_tool_call callback a specialist node passes to run_specialist()."""

    def on_tool_call(tool: str, args: dict) -> None:
        emit("tool_called", agent=agent, tool=tool, args={k: _short(v) for k, v in args.items()})

    return on_tool_call
