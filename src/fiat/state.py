from dataclasses import dataclass
from typing import Optional

@dataclass
class SessionState:
    provider: str = "Unknown"
    model: str = "Unknown"
    context_window: Optional[int] = None
    input_tokens: int = 0
    output_tokens: int = 0
    tool_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    estimated_cost: Optional[float] = None
    
    agent_status: str = "Idle"
    current_role: str = "—"
    current_iteration: int = 0
    max_iterations: int = 0

session_state = SessionState()

CONTEXT_WINDOWS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16384,
    "claude-3-5-sonnet-20240620": 200000,
    "claude-3-opus-20240229": 200000,
    "claude-3-haiku-20240307": 200000,
    "gemini-1.5-pro": 2000000,
    "gemini-1.5-flash": 1000000,
    "gemini-1.0-pro": 32768,
    "llama3-8b-8192": 8192,
    "llama3-70b-8192": 8192,
    "mixtral-8x7b-32768": 32768,
    "llama-3.3-70b-versatile": 131072,
    "openai/gpt-4o": 128000,
    "anthropic/claude-3-5-sonnet": 200000,
    "meta-llama/llama-3-70b-instruct": 8192
}

def update_context_window(model_name: str):
    session_state.context_window = CONTEXT_WINDOWS.get(model_name, None)

