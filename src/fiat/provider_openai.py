import json
import inspect
from typing import List, Callable, Generator
from openai import OpenAI
from fiat.providers import Provider

class OpenAIProvider(Provider):
    def __init__(self, system_prompt: str, base_url: str = None, provider_name: str = "OpenAI"):
        self.system_prompt = system_prompt
        self.client = None
        self.tools = []
        self.model = "gpt-4o"
        self.api_key = None
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.base_url = base_url
        self._provider_name = provider_name
        self._tool_map = {}

    @property
    def name(self) -> str:
        return self._provider_name

    def configure(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
        kwargs = {"api_key": api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self.client = OpenAI(**kwargs)

    def set_tools(self, tools: List[Callable]):
        self.tools = tools
        self._tool_map = {t.__name__: t for t in tools}

    def _type_map(self, py_type):
        if py_type == int: return "integer"
        if py_type == float: return "number"
        if py_type == bool: return "boolean"
        if py_type == list or getattr(py_type, "__origin__", None) == list: return "array"
        return "string"

    def _get_openai_tools(self):
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
                "type": "function",
                "function": {
                    "name": t.__name__,
                    "description": f"Call {t.__name__}",
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required
                    }
                }
            })
        return tools

    def stream(self, prompt: str) -> Generator[str, None, None]:
        if not self.client:
            raise RuntimeError("Provider not configured")
        
        self.messages.append({"role": "user", "content": prompt})
        tools = self._get_openai_tools()

        while True:
            kwargs = {
                "model": self.model,
                "messages": self.messages,
                "stream": True,
                "stream_options": {"include_usage": True}
            }
            if tools:
                kwargs["tools"] = tools

            response = self.client.chat.completions.create(**kwargs)
            
            tool_calls_dict = {}
            collected_content = ""
            
            from fiat.state import session_state
            session_state.requests += 1

            for chunk in response:
                if chunk.usage:
                    session_state.input_tokens = chunk.usage.prompt_tokens
                    session_state.output_tokens = chunk.usage.completion_tokens
                    session_state.total_tokens = chunk.usage.total_tokens

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                if delta.content:
                    collected_content += delta.content
                    yield delta.content
                
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.index not in tool_calls_dict:
                            tool_calls_dict[tc.index] = {"id": tc.id, "type": "function", "function": {"name": tc.function.name or "", "arguments": tc.function.arguments or ""}}
                        else:
                            if tc.function.name:
                                tool_calls_dict[tc.index]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_dict[tc.index]["function"]["arguments"] += tc.function.arguments

            # If there were tool calls, we must execute them and continue the loop
            if tool_calls_dict:
                tool_calls = list(tool_calls_dict.values())
                # Append the assistant message with tool calls
                self.messages.append({
                    "role": "assistant",
                    "content": collected_content or None,
                    "tool_calls": tool_calls
                })
                
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args_str = tc["function"]["arguments"]
                    try:
                        args = json.loads(fn_args_str)
                    except json.JSONDecodeError:
                        args = {}
                        
                    result = ""
                    if fn_name in self._tool_map:
                        try:
                            # To support the TodoWrite list correctly, we might need a custom parse if args are objects
                            # but simple json.loads is fine for now
                            res = self._tool_map[fn_name](**args)
                            result = str(res)
                        except Exception as e:
                            result = f"Error: {str(e)}"
                    else:
                        result = f"Unknown function: {fn_name}"
                        
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": result
                    })
                
                # Continue loop to send tool results
                continue
                
            else:
                # No tool calls, just normal response
                self.messages.append({"role": "assistant", "content": collected_content})
                break

    def supports_tools(self) -> bool:
        return True
