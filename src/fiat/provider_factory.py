from typing import Optional
from fiat.providers import Provider
from fiat.provider_gemini import GeminiProvider
from fiat.provider_openai import OpenAIProvider
from fiat.provider_anthropic import AnthropicProvider

class ProviderFactory:
    @staticmethod
    def create(provider_name: str, system_prompt: str) -> Optional[Provider]:
        name_lower = provider_name.lower()
        if name_lower == "gemini":
            return GeminiProvider(system_prompt=system_prompt)
        elif name_lower == "openai":
            return OpenAIProvider(system_prompt=system_prompt, provider_name="OpenAI")
        elif name_lower == "anthropic":
            return AnthropicProvider(system_prompt=system_prompt)
        elif name_lower == "openrouter":
            return OpenAIProvider(
                system_prompt=system_prompt, 
                base_url="https://openrouter.ai/api/v1",
                provider_name="OpenRouter"
            )
        elif name_lower == "groq":
            return OpenAIProvider(
                system_prompt=system_prompt, 
                base_url="https://api.groq.com/openai/v1",
                provider_name="Groq"
            )
        return None
