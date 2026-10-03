"""Run one specialist from the command line and print its tool calls and findings.

Usage: uv run python scripts/run_agent.py <agent> "<task>" [--group oncology]
"""

import argparse
import asyncio
import json
import re

from astra.agents.react_agent import run_specialist
from astra.agents.registry import AGENTS
from astra.config import CONDITION_GROUPS, configure_logging
from astra.db import close_pool


def print_tool_call(tool: str, args: dict) -> None:
    print(f"  -> {tool}({json.dumps(args)})")


async def main() -> None:
    parser = argparse.ArgumentParser(prog="run_agent.py")
    parser.add_argument("agent", choices=list(AGENTS))
    parser.add_argument("task")
    parser.add_argument("--group", choices=list(CONDITION_GROUPS))
    args = parser.parse_args()
    configure_logging()

    print(f"{args.agent}: {args.task}")
    try:
        result = await run_specialist(
            AGENTS[args.agent],
            args.task,
            run_id=None,
            focus_nct_ids=re.findall(r"NCT\d{8}", args.task.upper()),
            condition_group=args.group,
            on_tool_call=print_tool_call,
        )
    finally:
        await close_pool()

    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
