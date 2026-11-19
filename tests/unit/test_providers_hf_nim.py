"""Tests for HuggingFace and NVIDIA NIM provider registration, credential
resolution, and error classification."""

import os
from unittest.mock import MagicMock, patch

from fiat.provider_factory import ProviderFactory
from fiat.config import get_credential
from fiat.provider_errors import (
    ProviderPayloadTooLargeError,
    classify_provider_exception,
)


# ---------------------------------------------------------------------------
# 1. Factory / registry resolution
# ---------------------------------------------------------------------------

def test_factory_resolves_huggingface_with_correct_base_url():
    provider = ProviderFactory.create("huggingface", "You are a helpful assistant.")
    assert provider is not None
    assert provider.name == "HuggingFace"
    assert provider.base_url == "https://router.huggingface.co/v1"


def test_factory_resolves_nvidia_nim_with_correct_base_url():
    provider = ProviderFactory.create("nvidia_nim", "You are a helpful assistant.")
    assert provider is not None
    assert provider.name == "NVIDIA_NIM"
    assert provider.base_url == "https://integrate.api.nvidia.com/v1"


# ---------------------------------------------------------------------------
# 2. Credential resolution via env vars
# ---------------------------------------------------------------------------

def test_huggingface_credential_from_hf_token():
    with patch.dict(os.environ, {"HF_TOKEN": "hf-secret-123"}, clear=False):
        # Remove the generic key so the alias path is exercised
        os.environ.pop("HUGGINGFACE_API_KEY", None)
        cred = get_credential("HuggingFace")
        assert cred == "hf-secret-123"


def test_huggingface_credential_from_hub_token():
    with patch.dict(
        os.environ,
        {"HUGGINGFACEHUB_API_TOKEN": "hub-token-456"},
        clear=False,
    ):
        os.environ.pop("HUGGINGFACE_API_KEY", None)
        os.environ.pop("HF_TOKEN", None)
        cred = get_credential("HuggingFace")
        assert cred == "hub-token-456"


def test_nvidia_nim_credential_from_nvidia_api_key():
    with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-xyz"}, clear=False):
        os.environ.pop("NVIDIA_NIM_API_KEY", None)
        cred = get_credential("NVIDIA_NIM")
        assert cred == "nvapi-xyz"


# ---------------------------------------------------------------------------
# 3. Mocked streaming & error classification
# ---------------------------------------------------------------------------

def _build_configured_provider(name: str, api_key: str = "test-key"):
    """Create and configure a provider without hitting the network."""
    provider = ProviderFactory.create(name, "system")
    # Patch the OpenAI client so .configure() doesn't connect
    with patch("fiat.provider_openai.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        provider.configure(model="test-model", api_key=api_key)
    return provider, mock_client


def test_huggingface_mocked_stream_returns_content():
    provider, mock_client = _build_configured_provider("huggingface")

    # Build a minimal streaming response that the OpenAI provider can consume
    mock_chunk = MagicMock()
    mock_chunk.usage = None
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Hello from HF!"
    mock_chunk.choices[0].delta.tool_calls = None

    mock_client.chat.completions.create.return_value = iter([mock_chunk])

    chunks = list(provider.stream("hi"))
    assert "Hello from HF!" in chunks


def test_nvidia_nim_mocked_stream_returns_content():
    provider, mock_client = _build_configured_provider("nvidia_nim")

    mock_chunk = MagicMock()
    mock_chunk.usage = None
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Hello from NIM!"
    mock_chunk.choices[0].delta.tool_calls = None

    mock_client.chat.completions.create.return_value = iter([mock_chunk])

    chunks = list(provider.stream("hi"))
    assert "Hello from NIM!" in chunks


def test_classify_413_payload_too_large():
    """classify_provider_exception turns a 413-like error into ProviderPayloadTooLargeError."""
    exc = Exception("context_length_exceeded: requested 200000 tokens, limit 128000")
    classified = classify_provider_exception(exc)
    assert isinstance(classified, ProviderPayloadTooLargeError)
    assert classified.requested_tokens == 200000
    assert classified.limit_tokens == 128000


def test_classify_oversize_string_match():
    exc = Exception("Request too large for model: payload too large")
    classified = classify_provider_exception(exc)
    assert isinstance(classified, ProviderPayloadTooLargeError)


def test_classify_passthrough_for_unknown_error():
    exc = RuntimeError("something unrelated")
    classified = classify_provider_exception(exc)
    assert classified is exc
    assert not isinstance(classified, ProviderPayloadTooLargeError)
