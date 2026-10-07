import logging
from typing import List, Callable, Generator
from google import genai
from google.genai import types
from fiat.providers import Provider
import os

class GeminiProvider(Provider):
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.client = None
        self.chat_session = None
        self.tools = []
        self.model = "gemini-3.5-flash-lite"
        self.api_key = None

    @property
    def name(self) -> str:
        return "Gemini"

    def configure(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=5,
                    initial_delay=2.0,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                )
            ),
        )
        self._init_chat()

    def set_tools(self, tools: List[Callable]):
        self.tools = tools
        if self.client:
            self._init_chat()

    def _init_chat(self):
        if not self.client:
            return
        self.chat_session = self.client.chats.create(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                tools=self.tools if self.tools else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=30
                ) if self.tools else None,
            ),
        )

    def stream(self, prompt: str) -> Generator[str, None, None]:
        if not self.chat_session:
            raise RuntimeError("Provider not configured")
        
        from fiat.state import session_state
        session_state.requests += 1

        response_stream = self.chat_session.send_message_stream(prompt)
        for chunk in response_stream:
            if getattr(chunk, 'usage_metadata', None):
                session_state.input_tokens = chunk.usage_metadata.prompt_token_count
                session_state.output_tokens = chunk.usage_metadata.candidates_token_count
                session_state.total_tokens = chunk.usage_metadata.total_token_count

            if chunk.text:
                yield chunk.text

    def supports_tools(self) -> bool:
        return True
