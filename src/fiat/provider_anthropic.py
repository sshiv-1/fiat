import json
import inspect
from typing import List, Callable, Generator
from anthropic import Anthropic
from fiat.providers import Provider

class AnthropicProvider(Provider):
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.client = None
        self.tools = []
        self.model = "claude-3-5-sonnet-20240620"
        self.api_key = None
        self.messages = []
        self._tool_map = {}

    @property
    def name(self) -> str:
        return "Anthropic"

    def configure(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
        self.client = Anthropic(api_key=api_key)

    def set_tools(self, tools: List[Callable]):
        self.tools = tools
        self._tool_map = {t.__name__: t for t in tools}

    def _type_map(self, py_type):
        if py_type == int: return "integer"
        if py_type == float: return "number"
        if py_type == bool: return "boolean"
        if py_type == list or getattr(py_type, "__origin__", None) == list: return "array"
        return "string"

    def _get_anthropic_tools(self):
        if not self.tools:
            return None
        tools = []
        for t in self.tools:
            sig = inspect.signature(t)
            props = {}
            required = []
            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                props[name] = {"type": self._type_map(param.annotation)}
                if param.default == inspect.Parameter.empty:
                    required.append(name)
            
            tools.append({
                "name": t.__name__,
                "description": f"Call {t.__name__}",
                "input_schema": {
                    "type": "object",
                    "properties": props,
                    "required": required
                }
            })
        return tools

    def stream(self, prompt: str) -> Generator[str, None, None]:
        if not self.client:
            raise RuntimeError("Provider not configured")
        
        self.messages.append({"role": "user", "content": prompt})
        tools = self._get_anthropic_tools()

        while True:
            kwargs = {
                "model": self.model,
                "system": self.system_prompt,
                "messages": self.messages,
                "max_tokens": 4096
            }
            if tools:
                kwargs["tools"] = tools

            # Anthropic streaming
            response_stream = self.client.messages.create(**kwargs, stream=True)
            
            collected_text = ""
            current_tool_call = None
            tool_calls = []

            from fiat.state import session_state
            session_state.requests += 1

            for event in response_stream:
                if event.type == "message_start":
                    if getattr(event.message, 'usage', None):
                        session_state.input_tokens = getattr(event.message.usage, 'input_tokens', session_state.input_tokens)
                elif event.type == "message_delta":
                    if getattr(event, 'usage', None):
                        # Anthropic sends output_tokens delta or cumulative?
                        # It sends cumulative output_tokens in message_delta
                        session_state.output_tokens = getattr(event.usage, 'output_tokens', session_state.output_tokens)
                        session_state.total_tokens = session_state.input_tokens + session_state.output_tokens
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        current_tool_call = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input": ""
                        }
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        collected_text += event.delta.text
                        yield event.delta.text
                    elif event.delta.type == "input_json_delta":
                        if current_tool_call:
                            current_tool_call["input"] += event.delta.partial_json
                elif event.type == "content_block_stop":
                    if current_tool_call:
                        tool_calls.append(current_tool_call)
                        current_tool_call = None

            # Append the assistant response to messages
            assistant_content = []
            if collected_text:
                assistant_content.append({"type": "text", "text": collected_text})
            
            for tc in tool_calls:
                # Need to parse json string
                try:
                    parsed_input = json.loads(tc["input"])
                except Exception:
                    parsed_input = {}
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": parsed_input
                })

            if not assistant_content:
                # Sometimes it might just output empty?
                pass
            else:
                self.messages.append({"role": "assistant", "content": assistant_content})

            if tool_calls:
                tool_results = []
                for tc in tool_calls:
                    fn_name = tc["name"]
                    try:
                        args = json.loads(tc["input"])
                    except json.JSONDecodeError:
                        args = {}
                        
                    result = ""
                    if fn_name in self._tool_map:
                        try:
                            res = self._tool_map[fn_name](**args)
                            result = str(res)
                        except Exception as e:
                            result = f"Error: {str(e)}"
                    else:
                        result = f"Unknown function: {fn_name}"
                        
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": result
                    })
                
                self.messages.append({
                    "role": "user",
                    "content": tool_results
                })
                continue
            else:
                break

    def supports_tools(self) -> bool:
        return True
