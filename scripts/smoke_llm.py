"""Quick OpenRouter sanity check: uv run python scripts/smoke_llm.py"""

import asyncio

from langchain_core.tools import tool
from pydantic import BaseModel

from astra.config import settings
from astra.llm import plain_model, structured_model, tool_model, usage_of


@tool
def count_trials(condition_group: str) -> int:
    """Count the trials stored for a condition group, e.g. 'oncology'."""
    return 42


class Finding(BaseModel):
    nct_id: str
    confidence: float


async def main() -> None:
    print(f"strong={settings.strong_model} fast={settings.fast_model}")
    print(f"providers={settings.openrouter_provider_list}")

    reply = await plain_model("fast").ainvoke("Reply with the single word: pong")
    print(f"plain call:      {reply.text!r}")
    print(f"served by:       {reply.response_metadata.get('model_name')}")
    print(f"usage_metadata:  (input, output) = {usage_of(reply)}")

    reply = await tool_model("fast", [count_trials]).ainvoke(
        "How many oncology trials are stored? Use the tool."
    )
    print(f"tool call:       {reply.tool_calls}")

    output = await structured_model("fast", Finding).ainvoke(
        "Trial NCT01234567 is 60 months overdue posting results. Report it with confidence 0.9."
    )
    print(f"structured call: {output['parsed']!r}, usage {usage_of(output['raw'])}")


if __name__ == "__main__":
    asyncio.run(main())
