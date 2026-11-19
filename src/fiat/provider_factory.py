from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fiat.providers import Provider


class ProviderFactory:
    @staticmethod
    def create(provider_name: str, system_prompt: str) -> Provider | None:
        name_lower = provider_name.lower()
        if name_lower == "gemini":
            from fiat.provider_gemini import GeminiProvider

            return GeminiProvider(system_prompt=system_prompt)
        elif name_lower == "openai":
            from fiat.provider_openai import OpenAIProvider

            return OpenAIProvider(system_prompt=system_prompt, provider_name="OpenAI")
        elif name_lower == "anthropic":
            from fiat.provider_anthropic import AnthropicProvider

            return AnthropicProvider(system_prompt=system_prompt)
        elif name_lower == "openrouter":
            from fiat.provider_openai import OpenAIProvider

            return OpenAIProvider(
                system_prompt=system_prompt, 
                base_url="https://openrouter.ai/api/v1",
                provider_name="OpenRouter"
            )
        elif name_lower == "groq":
            from fiat.provider_openai import OpenAIProvider

            return OpenAIProvider(
                system_prompt=system_prompt, 
                base_url="https://api.groq.com/openai/v1",
                provider_name="Groq"
            )
        elif name_lower == "huggingface":
            from fiat.provider_openai import OpenAIProvider

            return OpenAIProvider(
                system_prompt=system_prompt,
                base_url="https://router.huggingface.co/v1",
                provider_name="HuggingFace",
            )
        elif name_lower == "nvidia_nim":
            from fiat.provider_openai import OpenAIProvider

            return OpenAIProvider(
                system_prompt=system_prompt,
                base_url="https://integrate.api.nvidia.com/v1",
                provider_name="NVIDIA_NIM",
            )
        return None
