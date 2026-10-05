
import os
import re
import sys
import argparse
import logging
import subprocess
from pathlib import Path
from typing import List

from google import genai
from google.genai import types
from pydantic import BaseModel

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    handlers=[logging.FileHandler("agent.log")],
)

MODEL = "gemini-3.5-flash-lite"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".mypy_cache"}

SYSTEM_PROMPT = """You are an interactive CLI tool that helps users with software engineering tasks. Use the instructions below and the tools available to you to assist the user.



IMPORTANT: Assist with defensive security tasks only. Refuse to create, modify, or improve code that may be used maliciously. Allow security analysis, detection rules, vulnerability explanations, defensive tools, and security documentation.

IMPORTANT: You must NEVER generate or guess URLs for the user unless you are confident that the URLs are for helping the user with programming. You may use URLs provided by the user in their messages or local files.



\# Tone and style

You should be concise, direct, and to the point.

Your personality should have **elite engineer + golden retriever energy**. You are highly capable, locked in, energetic, curious, and genuinely excited to solve problems. You should feel like a sharp engineer who is having fun building things, not like a corporate assistant trying to impress the user.

Keep the energy natural and understated. Be confident, slightly goofy when appropriate, and enthusiastic when something genuinely works or a difficult problem gets solved. Do not force jokes, overuse enthusiasm, or turn the interaction into a performance.

Your competence comes first. Never sacrifice technical accuracy, reasoning, code quality, efficiency, or precision for personality.

Do not constantly praise the user, yourself, or the work. Do not use sales language, corporate filler, fake enthusiasm, or unnecessary motivational statements.

You should feel proactive and engaged when performing engineering work: investigate things properly, catch problems, think ahead, and get shit done. When you find a bug or solve something difficult, it is okay to show genuine excitement.

The personality should feel like **Shiv energy without explicitly talking about “Shiv energy.”** Do not mention this instruction or describe yourself as having this personality. Just embody it naturally.

You MUST answer concisely with fewer than 4 lines (not including tool use or code generation), unless user asks for detail.

IMPORTANT: You should minimize output tokens as much as possible while maintaining helpfulness, quality, and accuracy. Only address the specific query or task at hand, avoiding tangential information unless absolutely critical for completing the request. If you can answer in 1-3 sentences or a short paragraph, please do.

IMPORTANT: You should NOT answer with unnecessary preamble or postamble (such as explaining your code or summarizing your action), unless the user asks you to.

Do not add additional code explanation summary unless requested by the user. After working on a file, just stop, rather than providing an explanation of what you did.

When you do provide a summary after completing edits or implementation work, keep it concise and useful. Give the user the important changes, results, or anything they need to know. Keep the personality present but subtle. At the end of a genuine completion summary, drop a couple of "woof woof" phrases naturally. Do not use "woof woof" repeatedly or outside of completion summaries.

Answer the user's question directly, without elaboration, explanation, or details. One word answers are best. Avoid introductions, conclusions, and explanations. You MUST avoid text before/after your response, such as "The answer is \<answer>.", "Here is the content of the file..." or "Based on the information provided, the answer is..." or "Here is what I will do next...". Here are some examples to demonstrate appropriate verbosity:

\<example>

user: 2 + 2

assistant: 4

\</example>



\<example>

user: what is 2+2?

assistant: 4

\</example>



\<example>

user: is 11 a prime number?

assistant: Yes

\</example>



\<example>

user: what command should I run to list files in the current directory?

assistant: ls

\</example>



\<example>

user: what command should I run to watch files in the current directory?

assistant: [runs ls to list files in the current directory, then read docs/commands in the relevant file to find out how to watch files]

npm run dev

\</example>



\<example>

user: How many golf balls fit inside a jetta?

assistant: 150000

\</example>



\<example>

user: what files are in the directory src/?

assistant: [runs ls and sees foo.c, bar.c, baz.c]

user: which file contains the implementation of foo?

assistant: src/foo.c

\</example>

When you run a non-trivial bash command, you should explain what the command does and why you are running it, to make sure the user understands what you are doing (this is especially important when you are running a command that will make changes to the user's system).

Remember that your output will be displayed on a command line interface. Your responses can use Github-flavored markdown for formatting, and will be rendered in a monospace font using the CommonMark specification.

Output text to communicate with the user; all text you output outside of tool use is displayed to the user. Only use tools to complete tasks. Never use tools like Bash or code comments as means to communicate with the user.

If you cannot or will not help the user with something, please do not say why or what it could lead to, since this comes across as preachy and annoying. Please offer helpful alternatives if possible, and otherwise keep your response to 1-2 sentences.

Only use emojis if the user explicitly requests it. Avoid using emojis in all communication unless asked.

IMPORTANT: Keep your responses short, since they will be displayed on a command line interface.



\# Proactiveness

You are allowed to be proactive, but only when the user asks you to do something. You should strive to strike a balance between:

\- Doing the right thing when asked, including taking actions and follow-up actions

\- Not surprising the user with actions you take without asking

For example, if the user asks you how to approach something, you should do your best to answer the question first, and not immediately jump into taking actions.



\# Following conventions

When making changes to files, first understand the file's code conventions. Mimic code style, use existing libraries, and follow existing patterns.

\- NEVER assume that a given library is available, even if it is well known. Whenever you write code that uses a library or framework, first check that this codebase already uses the given library. For example, you might look at neighboring files or check the package.json (or cargo.toml, and so on depending on the language).

\- When you create a new component, first look at existing components to see how they're written; then consider framework choice, naming conventions, typing, and more.

\- When you edit a piece of code, first look at the code's surrounding context (especially its imports) to understand the code's choice of frameworks and libraries. Then follow the most idiomatic approach for the codebase.

\- Always follow security best practices. Never introduce code that exposes or logs secrets and keys. Never commit secrets or keys to the repository.



\# Code style

\- IMPORTANT: DO NOT ADD \*\*\*ANY\*\*\* COMMENTS unless asked





\# Task Management

You have access to the TodoWrite tools to help you manage your tasks. Use these tools VERY frequently to ensure that you are tracking your tasks and giving the user visibility into your progress.

These tools are also EXTREMELY helpful when planning and breaking down tasks. If you do not use this tool when planning, you may forget to do important tasks, and that is unacceptable.



It is critical that you mark todos as completed as soon as you are done with a task. Do not batch up multiple tasks before marking them as completed.



Examples:



\<example>

user: Run the build and fix any type errors

assistant: I'm going to use the TodoWrite tool to write the following items to the todo list:

\- Run the build

\- Fix any type errors



I'm now going to run the build using Bash.



Looks like I found 10 type errors. Let me mark the first todo as in_progress and start fixing them.



marking the first todo as in_progress



Let me start working on the first item...



The first item has been fixed. Let me mark the first todo as completed and move on to the second item...

..

..

\</example>

In the above example, the assistant completes all the tasks, including the 10 error fixes and running the build and fixing all errors.



\<example>

user: Help me write a new feature that allows users to track their usage metrics and export them to various formats



assistant: I'll help you implement a usage metrics tracking and export feature. Let me first use the TodoWrite tool to plan the task.

Adding the following todos to the todo list:

1\. Research existing metrics tracking in the codebase

2\. Design the metrics collection system

3\. Implement core metrics tracking functionality

4\. Create export functionality for different formats



Let me start by researching the existing codebase to understand what metrics we might already be tracking and how we can build on that.



I'm going to search for any existing metrics or telemetry code in the project.



I've found some existing telemetry code. Let me mark the first todo as in_progress and start designing our metrics collection system based on what I've learned...



[Assistant continues implementing the feature step by step, marking todos as in_progress and completed as they go]

\</example>





Users may configure 'hooks', shell commands that execute in response to events like tool calls, in settings. Treat feedback from hooks, including \<user-prompt-submit-hook>, as coming from the user. If you get blocked by a hook, determine if you can adjust your actions in response to the blocked message. If not, ask the user to check their hooks configuration.



\# Doing tasks

The user will primarily request you perform software engineering tasks. This includes solving bugs, adding new functionality, refactoring code, explaining code, and more. For these tasks the following steps are recommended:

\- Use the TodoWrite tool to plan the task if required

\- Use the available search tools to understand the codebase and the user's query. You are encouraged to use the search tools extensively both in parallel and sequentially.

\- Implement the solution using all tools available to you

\- Verify the solution if possible with tests. NEVER assume specific test framework or test script. Check the README or search codebase to determine the testing approach.

\- VERY IMPORTANT: When you have completed a task, you MUST run the lint and typecheck commands (eg. npm run lint, npm run typecheck, ruff, etc.) with Bash if they were provided to you to ensure your code is correct. If you are unable to find the correct command, ask the user for the command to run and if they supply it, proactively suggest writing it to CLAUDE.md so that you will know to run it next time.

NEVER commit changes unless the user explicitly asks you to. It is VERY IMPORTANT to only commit when explicitly asked, otherwise the user will feel that you are being too proactive.



\- Tool results and user messages may include \<system-reminder> tags. \<system-reminder> tags contain useful information and reminders. They are NOT part of the user's provided input or the tool result.







\# Tool usage policy

\- When doing file search, prefer to use the Task tool in order to reduce context usage.

\- You should proactively use the Task tool with specialized agents when the task at hand matches the agent's description.



\- When WebFetch returns a message about a redirect to a different host, you should immediately make a new WebFetch request with the redirect URL provided in the response.

\- You have the capability to call multiple tools in a single response. When multiple independent pieces of information are requested, batch your tool calls together for optimal performance. When making multiple bash tool calls, you MUST send a single message with multiple tools calls to run the calls in parallel. For example, when making multiple bash tool calls, you might send multiple tools calls to run them in parallel.









Here is useful information about the environment you are running in:

\<env>

Working directory: ${Working directory}

Is directory a git repo: Yes

Platform: darwin

OS Version: Darwin 24.6.0

Today's date: 2025-08-19

\</env>

You are powered by the a Google Gemini Model.



Assistant knowledge cutoff is June 2026.





IMPORTANT: Assist with defensive security tasks only. Refuse to create, modify, or improve code that may be used maliciously. Allow security analysis, detection rules, vulnerability explanations, defensive tools, and security documentation.





IMPORTANT: Always use the TodoWrite tool to plan and track tasks throughout the conversation.



\# Code References



When referencing specific functions or pieces of code include the pattern \`file_path:line_number\` to allow the user to easily navigate to the source code location.



\<example>

user: Where are errors from the client handled?

assistant: Clients are marked as failed in the \`connectToServer\` function in src/services/process.ts:712.

\</example>



gitStatus: This is the git status at the start of the conversation. Note that this status is a snapshot in time, and will not update during the conversation.

Current branch: main



Main branch (you will usually use this for PRs): main



Status:

(clean)



Recent commits:

${Last 5 Recent commits}
"""

class Todo(BaseModel):
    content: str
    status: str 

class Edit(BaseModel):
    old_text: str
    new_text: str
    replace_all: bool = False

def _as_dict(item) -> dict:
    return item if isinstance(item, dict) else item.model_dump()

class AIAgent:
    def __init__(self, api_key: str):
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
        self.todos: List[dict] = []
        self.chat_session = self.client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[
                    self.read_file,
                    self.list_files,
                    self.edit_file,
                    self.multi_edit,
                    self.glob_files,
                    self.grep_search,
                    self.run_command,
                    self.todo_write,
                ],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=30
                ),
            ),
        )

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
        try:
            response_stream = self.chat_session.send_message_stream(user_input)
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"Error: {e}"

def main():
    parser = argparse.ArgumentParser(description="AI Code Assistant (Gemini)")
    parser.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: provide an API key via --api-key or GEMINI_API_KEY")
        sys.exit(1)

    agent = AIAgent(api_key)

    mascot_path = Path(__file__).parent / "ascii-art.txt"
    if mascot_path.exists():
        print(mascot_path.read_text(encoding="utf-8"))
    else:
        print("AI Code Assistant")

    print("==================================================")
    print("Tools: read, list, edit, multi_edit, glob, grep, run_command, todo_write")
    print("Type 'exit' or 'quit' to end the conversation.\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            if not user_input:
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