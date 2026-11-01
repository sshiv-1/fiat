import pytest

from fiat.provider_factory import ProviderFactory
from fiat.provider_openai import OpenAIProvider


def test_provider_factory_preserves_known_provider_adapters():
    assert ProviderFactory.create("OpenAI", "system").name == "OpenAI"
    assert ProviderFactory.create("OpenRouter", "system").name == "OpenRouter"
    assert ProviderFactory.create("unknown", "system") is None


def test_openai_provider_configure_uses_mocked_client(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("fiat.provider_openai.OpenAI", FakeOpenAI)
    provider = OpenAIProvider("system")
    provider.configure("fake-model", "not-a-real-key")

    assert provider.model == "fake-model"
    assert captured == {"api_key": "not-a-real-key"}


def test_provider_requires_configuration_before_streaming():
    provider = OpenAIProvider("system")

    with pytest.raises(RuntimeError, match="not configured"):
        next(provider.stream("hello"))


def test_openai_provider_builds_tool_schema_without_network_calls():
    def read_item(path: str, count: int = 1) -> str:
        return path * count

    provider = OpenAIProvider("system")
    provider.set_tools([read_item])

    tools = provider._get_openai_tools()

    assert tools[0]["function"]["name"] == "read_item"
    assert tools[0]["function"]["parameters"]["required"] == ["path"]
