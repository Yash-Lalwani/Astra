import os

from langchain_core.messages import AIMessage

from astra.config import Settings, export_langsmith_env
from astra.llm import usage_of


def test_langsmith_settings_are_exported_to_environ(monkeypatch):
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    config = Settings(langsmith_api_key="test-key", langsmith_project="astra-test")
    export_langsmith_env(config)
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "test-key"
    assert os.environ["LANGSMITH_PROJECT"] == "astra-test"


def test_usage_of_reads_usage_metadata():
    message = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    )
    assert usage_of(message) == (120, 30)


def test_usage_of_without_usage_metadata():
    assert usage_of(AIMessage(content="ok")) == (0, 0)
