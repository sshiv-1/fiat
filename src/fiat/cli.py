import argparse
import logging
import sys
import time
from pathlib import Path

import pwinput
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from pydantic import BaseModel

from fiat.config import (
    CONFIG_DIR,
    AuthConfig,
    ProviderConfig,
    get_credential,
    load_config,
    save_config,
    save_credential,
)
from fiat.prompt import SYSTEM_PROMPT
from fiat.provider_factory import ProviderFactory
from fiat.providers import Provider
from fiat.repository.repo_map import run_repository_command
from fiat.tools import (
    FileSystemTools,
    TerminalExecutor,
    TerminalResult,
    WorkspaceManager,
)
from fiat.ui import interactive_select

load_dotenv()

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    handlers=[logging.FileHandler(CONFIG_DIR / "agent.log")],
)

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
    def __init__(self, workspace_root: str | Path | None = None):
        self.provider: Provider | None = None
        self.todos: list[dict] = []
        self.workspace = WorkspaceManager(workspace_root or Path.cwd())
        self.filesystem = FileSystemTools(self.workspace)
        self.terminal = TerminalExecutor(self.workspace)
        self.command_history: list[tuple[str, TerminalResult]] = []
        
    def setup_provider(self, config: ProviderConfig, api_key: str):
        started_at = time.perf_counter()
        logging.info("Initializing %s provider.", config.provider_name)
        try:
            self.provider = ProviderFactory.create(config.provider_name, SYSTEM_PROMPT)
            if not self.provider:
                raise ValueError(f"Unknown provider: {config.provider_name}")

            self.provider.configure(model=config.model_name, api_key=api_key)
        except KeyboardInterrupt:
            elapsed = time.perf_counter() - started_at
            logging.warning(
                "Provider initialization interrupted after %.2fs (%s).",
                elapsed,
                config.provider_name,
            )
            raise
        else:
            elapsed = time.perf_counter() - started_at
            logging.info(
                "Provider %s initialized in %.2fs.",
                config.provider_name,
                elapsed,
            )
        
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

    def read_file(self, path: str) -> str:
        self._log_tool("read_file", path)
        return self.filesystem.read_file(path)

    def list_files(self, path: str = ".") -> str:
        self._log_tool("list_files", path)
        return self.filesystem.list_files(path)

    def edit_file(self, path: str, new_text: str, old_text: str = "", replace_all: bool = False) -> str:
        self._log_tool("edit_file", path)
        return self.filesystem.edit_file(path, new_text, old_text, replace_all)

    def multi_edit(self, path: str, edits: list[Edit]) -> str:
        self._log_tool("multi_edit", f"{path} ({len(edits)} edits)")
        return self.filesystem.multi_edit(path, edits)

    def glob_files(self, pattern: str, path: str = ".") -> str:
        self._log_tool("glob_files", f"{pattern} in {path}")
        return self.filesystem.glob_files(pattern, path)

    def grep_search(self, pattern: str, path: str = ".", file_glob: str = "*", ignore_case: bool = False) -> str:
        self._log_tool("grep_search", f"{pattern!r} in {path}")
        return self.filesystem.grep_search(pattern, path, file_glob, ignore_case)

    def run_command(self, command: str, timeout_seconds: int = 60) -> str:
        self._log_tool("run_command", "request received")

        def approve(request):
            rendered = " ".join(request.args)
            answer = input(f"\n  Approve command? [y/N]: {rendered}\n  > ").strip().lower()
            return answer in ("y", "yes")

        result = self.terminal.execute(command, timeout_seconds, approve)
        from fiat.state import session_state

        self.command_history.append((session_state.current_role, result))
        return result.format()

    def todo_write(self, todos: list[Todo]) -> str:
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
            yield from orchestrator.run(user_input)
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
        "name": "/index",
        "description": "Scan the workspace and save safe index metadata.",
    },
    {
        "name": "/map",
        "description": "Show the current repository map.",
    },
    {
        "name": "/search",
        "description": "Search indexed repository text with a regex query.",
    },
    {
        "name": "/symbol",
        "description": "Find indexed symbols by name.",
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
    parser.add_argument("--workspace", default=".", help="Workspace for repository commands")
    parser.add_argument("repository_command", nargs="?", help="/index, /map, /search, or /symbol")
    parser.add_argument("repository_query", nargs="*", help="Arguments for a repository command")
    args = parser.parse_args()

    if args.repository_command:
        repository_commands = {"/index", "/map", "/search", "/symbol"}
        command = args.repository_command.casefold()
        if command not in repository_commands:
            parser.error(f"Unknown command: {args.repository_command}")
        try:
            workspace = WorkspaceManager(args.workspace)
            print(run_repository_command(command, args.repository_query, workspace))
        except (OSError, ValueError) as error:
            parser.error(str(error))
        return

    config = load_config()
    if not config:
        config = run_first_time_setup()

    api_key = args.api_key or get_credential(config.provider_name)
    if not api_key:
        print(f"Error: API key for {config.provider_name} not found.")
        print(f"Please set {config.provider_name.upper()}_API_KEY or run setup again.")
        sys.exit(1)

    agent = FiatCore()
    try:
        agent.setup_provider(config, api_key)
    except KeyboardInterrupt:
        print(f"\nStartup interrupted while initializing {config.provider_name}.")
        return 130
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
            command_name, _, command_arguments = user_input.partition(" ")
            repository_commands = {"/index", "/map", "/search", "/symbol"}
            
            if lower_input == "/":
                print("\nCommands:")
                for cmd in COMMANDS:
                    print(f"  {cmd['name'].ljust(12)} {cmd['description']}")
                print()
                continue
                
            if command_name.casefold() in repository_commands:
                print(
                    "\n"
                    + run_repository_command(
                        command_name.casefold(),
                        command_arguments.split() if command_arguments else [],
                        agent.workspace,
                    )
                    + "\n"
                )
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
