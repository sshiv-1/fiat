import os
import re
import sys
import argparse
import logging
import subprocess
import pwinput
from pathlib import Path
from typing import List

from pydantic import BaseModel
from dotenv import load_dotenv

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

from fiat.ui import interactive_select
from fiat.prompt import SYSTEM_PROMPT
from fiat.config import load_config, save_config, ProviderConfig, AuthConfig, get_credential, save_credential, CONFIG_DIR
from fiat.provider_factory import ProviderFactory

load_dotenv()

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    handlers=[logging.FileHandler(CONFIG_DIR / "agent.log")],
)

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".mypy_cache"}

class Todo(BaseModel):
    content: str
    status: str 

class Edit(BaseModel):
    old_text: str
    new_text: str
    replace_all: bool = False

def _as_dict(item) -> dict:
    return item if isinstance(item, dict) else item.model_dump()

class FiatCore:
    def __init__(self):
        self.provider = None
        self.todos: List[dict] = []
        
    def setup_provider(self, config: ProviderConfig, api_key: str):
        self.provider = ProviderFactory.create(config.provider_name, SYSTEM_PROMPT)
        if not self.provider:
            raise ValueError(f"Unknown provider: {config.provider_name}")
        
        self.provider.configure(model=config.model_name, api_key=api_key)
        
        self.provider.set_tools([
            self.read_file,
            self.list_files,
            self.edit_file,
            self.multi_edit,
            self.glob_files,
            self.grep_search,
            self.run_command,
            self.todo_write,
        ])

    @staticmethod
    def _log_tool(name: str, detail: str = ""):
        logging.info(f"{name}: {detail}")
        print(f"\n  [tool] {name} {detail}".rstrip(), flush=True)

    @staticmethod
    def _apply_edit(content: str, old: str, new: str, replace_all: bool) -> str:
        if not old:
            raise ValueError("old_text is empty")
        count = content.count(old)
        if count == 0:
            raise ValueError(f"text not found: {old[:80]!r}")
        if count > 1 and not replace_all:
            raise ValueError(
                f"text appears {count} times (add more context or set replace_all): {old[:80]!r}"
            )
        return content.replace(old, new) if replace_all else content.replace(old, new, 1)

    def read_file(self, path: str) -> str:
        self._log_tool("read_file", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f"File contents of {path}:\n{f.read()}"
        except FileNotFoundError:
            return f"File not found: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

    def list_files(self, path: str = ".") -> str:
        self._log_tool("list_files", path)
        try:
            if not os.path.exists(path):
                return f"Path not found: {path}"
            items = []
            for item in sorted(os.listdir(path)):
                if os.path.isdir(os.path.join(path, item)):
                    items.append(f"[DIR]  {item}/")
                else:
                    items.append(f"[FILE] {item}")
            if not items:
                return f"Empty directory: {path}"
            return f"Contents of {path}:\n" + "\n".join(items)
        except Exception as e:
            return f"Error listing files: {e}"

    def edit_file(self, path: str, new_text: str, old_text: str = "", replace_all: bool = False) -> str:
        self._log_tool("edit_file", path)
        try:
            if old_text and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                content = self._apply_edit(content, old_text, new_text, replace_all)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return f"Successfully edited {path}"

            dir_name = os.path.dirname(path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            return f"Successfully created {path}"
        except Exception as e:
            return f"Error editing file: {e}"

    def multi_edit(self, path: str, edits: List[Edit]) -> str:
        self._log_tool("multi_edit", f"{path} ({len(edits)} edits)")
        try:
            if not os.path.exists(path):
                return f"File not found: {path}"
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            for i, raw in enumerate(edits, start=1):
                e = _as_dict(raw)
                try:
                    content = self._apply_edit(
                        content, e["old_text"], e["new_text"], e.get("replace_all", False)
                    )
                except ValueError as err:
                    return f"Edit {i} failed, no changes written: {err}"

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully applied {len(edits)} edits to {path}"
        except Exception as e:
            return f"Error in multi_edit: {e}"

    def glob_files(self, pattern: str, path: str = ".") -> str:
        self._log_tool("glob_files", f"{pattern} in {path}")
        try:
            matches = [
                p for p in Path(path).glob(pattern)
                if p.is_file() and not (set(p.parts) & SKIP_DIRS)
            ]
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            if not matches:
                return f"No files matched {pattern}"
            return "\n".join(str(p) for p in matches[:200])
        except Exception as e:
            return f"Error in glob_files: {e}"

    def grep_search(self, pattern: str, path: str = ".", file_glob: str = "*", ignore_case: bool = False) -> str:
        self._log_tool("grep_search", f"{pattern!r} in {path}")
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            return f"Invalid regex: {e}"

        root = Path(path)
        files = [root] if root.is_file() else [
            p for p in root.rglob(file_glob)
            if p.is_file() and not (set(p.parts) & SKIP_DIRS)
        ]

        results = []
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for lineno, line in enumerate(f, start=1):
                        if regex.search(line):
                            results.append(f"{fp}:{lineno}:{line.rstrip()[:200]}")
                            if len(results) >= 200:
                                return "\n".join(results) + "\n(truncated at 200 matches)"
            except (UnicodeDecodeError, OSError):
                continue
        return "\n".join(results) if results else f"No matches for {pattern!r}"

    def run_command(self, command: str, timeout_seconds: int = 60) -> str:
        self._log_tool("run_command", command)
        answer = input(f"\n  Run this command? [y/N]: {command}\n  > ").strip().lower()
        if answer not in ("y", "yes"):
            return "User declined to run the command."
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout_seconds
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if len(out) > 8000:
                out = out[:8000] + "\n...(output truncated)"
            return f"Exit code {proc.returncode}\n{out}"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout_seconds}s"
        except Exception as e:
            return f"Error running command: {e}"

    def todo_write(self, todos: List[Todo]) -> str:
        self.todos = [_as_dict(t) for t in todos]
        self._log_tool("todo_write", f"({len(self.todos)} items)")
        icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        print("\n  Plan:")
        for t in self.todos:
            print(f"    {icons.get(t['status'], '[ ]')} {t['content']}")
        return "Todo list updated."

    def chat(self, user_input: str):
        from fiat.agents.orchestrator import Orchestrator
        orchestrator = Orchestrator(self)
        try:
            for chunk in orchestrator.run(user_input):
                yield chunk
        except Exception as e:
            yield f"\nError: {e}"


COMMANDS = [
    {
        "name": "/provider",
        "description": "View or change the current LLM provider.",
    },
    {
        "name": "/model",
        "description": "View or change the current model.",
    },
    {
        "name": "/auth",
        "description": "Configure or re-enter provider authentication.",
    },
    {
        "name": "/context",
        "description": "Show interactive context and usage dashboard.",
    },
    {
        "name": "/help",
        "description": "Show this command reference.",
    },
    {
        "name": "/exit",
        "description": "Exit Fiat.",
    },
    {
        "name": "/quit",
        "description": "Exit Fiat.",
    }
]

PROVIDER_MODELS = {
    "Gemini": ["gemini-3.5-flash-lite", "gemini-3.5-pro", "gemini-1.5-pro", "gemini-1.5-flash"],
    "OpenAI": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "Anthropic": ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-haiku-20240307"],
    "OpenRouter": ["openai/gpt-4o", "anthropic/claude-3-5-sonnet", "meta-llama/llama-3-70b-instruct"],
    "Groq": [
        "llama-3.3-70b-versatile",
        "llama3-8b-8192", 
        "llama3-70b-8192", 
        "mixtral-8x7b-32768",
        "openai/gpt-oss-120b",
        "minimaxai/minimax-m2.7",
        "deepseek-r1-distill-llama-70b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-safeguard-20b"
    ]
}

class CommandCompleter(Completer):
    def __init__(self, commands):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text
        if text.startswith('/'):
            for cmd in self.commands:
                if cmd["name"].startswith(text):
                    yield Completion(
                        cmd["name"],
                        start_position=-len(text),
                        display=cmd["name"].ljust(12),
                        display_meta=cmd["description"]
                    )

def run_first_time_setup() -> ProviderConfig:
    print("\nWelcome to Fiat. Let's set up your environment.\n")
    
    providers = ["Gemini", "OpenAI", "Anthropic", "OpenRouter", "Groq"]
    provider_name = interactive_select("Choose provider:", providers)
    if not provider_name:
        provider_name = "Gemini"
        print(f"Defaulting to {provider_name}")
    
    auth_method = "api_key"
    
    api_key = pwinput.pwinput(f"\nEnter API key for {provider_name}: ").strip()
    save_credential(provider_name, api_key)
    
    model_list = PROVIDER_MODELS.get(provider_name, ["default-model"])
    model_name = interactive_select("Choose model:", model_list)
    if not model_name:
        model_name = model_list[0]
        print(f"Defaulting to {model_name}")
    
    config = ProviderConfig(
        provider_name=provider_name,
        model_name=model_name,
        auth=AuthConfig(method=auth_method)
    )
    save_config(config)
    print("\nConfiguration saved.\n")
    return config


def main():
    parser = argparse.ArgumentParser(description="AI Code Assistant (Fiat)")
    parser.add_argument("--api-key", help="Fallback API key if not configured")
    args = parser.parse_args()

    config = load_config()
    if not config:
        config = run_first_time_setup()

    api_key = args.api_key or get_credential(config.provider_name)
    if not api_key:
        print(f"Error: API key for {config.provider_name} not found.")
        print(f"Please set {config.provider_name.upper()}_API_KEY or run setup again.")
        sys.exit(1)

    agent = FiatCore()
    agent.setup_provider(config, api_key)
    from fiat.state import session_state, update_context_window
    session_state.provider = config.provider_name
    session_state.model = config.model_name
    update_context_window(config.model_name)

    mascot_path = Path(__file__).parent / "ascii-art.txt"
    if mascot_path.exists():
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
        print(mascot_path.read_text(encoding="utf-8"))
    else:
        print("Fiat AI Assistant")

    print("==================================================")
    print("Tools: read, list, edit, multi_edit, glob, grep, run_command, todo_write")
    print("Commands: Type /help to see available commands")
    print(f"Current Provider: {config.provider_name} | Model: {config.model_name}\n")

    session = PromptSession(completer=CommandCompleter(COMMANDS))

    while True:
        try:
            user_input = session.prompt("You: ").strip()
            if not user_input:
                continue
                
            lower_input = user_input.lower()
            
            if lower_input == "/":
                print("\nCommands:")
                for cmd in COMMANDS:
                    print(f"  {cmd['name'].ljust(12)} {cmd['description']}")
                print()
                continue
                
            if lower_input.startswith("/") and lower_input not in [c["name"] for c in COMMANDS]:
                print(f"\nUnknown command: {lower_input}. Type /help for available commands.\n")
                continue

            if lower_input == "/help":
                print("\nFiat Commands\n")
                for cmd in COMMANDS:
                    print(f"{cmd['name']}")
                    print(f"  {cmd['description']}\n")
                continue

            if lower_input in ["/exit", "/quit"]:
                print("Goodbye!")
                break
                
            if lower_input == "/provider":
                print(f"\nCurrent provider: {config.provider_name}")
                providers = ["Gemini", "OpenAI", "Anthropic", "OpenRouter", "Groq"]
                new_provider = interactive_select("Choose provider:", providers)
                
                if new_provider and new_provider != config.provider_name:
                    print(f"\nSwitched to {new_provider}.")
                    new_key = get_credential(new_provider)
                    if not new_key:
                        new_key = pwinput.pwinput(f"Enter API key for {new_provider}: ").strip()
                        save_credential(new_provider, new_key)
                    
                    config.provider_name = new_provider
                    # Default model for new provider
                    model_list = PROVIDER_MODELS.get(new_provider, ["default-model"])
                    config.model_name = model_list[0]
                    save_config(config)
                    agent.setup_provider(config, new_key)
                    from fiat.state import session_state, update_context_window
                    session_state.provider = config.provider_name
                    session_state.model = config.model_name
                    update_context_window(config.model_name)
                    print(f"Provider switched to {new_provider} (Model: {config.model_name})")
                continue

            if lower_input == "/auth":
                print(f"\nCurrent provider: {config.provider_name}")
                print("\nAuthentication:")
                print("1. Re-enter API key")
                print("2. Cancel")
                auth_choice = input("\nSelect [1-2]: ").strip()
                
                if auth_choice == "1":
                    new_key = pwinput.pwinput(f"Enter new API key for {config.provider_name}: ").strip()
                    if new_key:
                        save_credential(config.provider_name, new_key)
                        agent.setup_provider(config, new_key)
                        print("API key updated successfully.")
                    else:
                        print("No key entered. Cancelled.")
                else:
                    print("Cancelled.")
                continue

            if lower_input == "/context":
                from fiat.context_ui import show_context_ui
                show_context_ui()
                continue
                
            if lower_input == "/model":
                print(f"\nCurrent model: {config.model_name}")
                model_list = PROVIDER_MODELS.get(config.provider_name, ["default-model"])
                
                # If they want to manually type a model not in the list, we can fallback to typing if questionary is aborted or we can just offer typing as a standard.
                # The user requested: "Esc from model selection preserves the existing model."
                new_model = interactive_select("Choose model:", model_list)
                
                if new_model and new_model != config.model_name:
                    config.model_name = new_model
                    save_config(config)
                    # Reconfigure provider
                    key = get_credential(config.provider_name)
                    agent.setup_provider(config, key)
                    from fiat.state import session_state, update_context_window
                    session_state.model = config.model_name
                    update_context_window(config.model_name)
                    print(f"Model updated to {config.model_name}")
                else:
                    print("Model change cancelled or unchanged.")
                continue

            print("\n Fiat: ", end="", flush=True)
            for chunk in agent.chat(user_input):
                print(chunk, end="", flush=True)
            print("\n")
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break

if __name__ == "__main__":
    main()
