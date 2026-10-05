Meet Fiat
A tiny Claude Code inspired coding agent that lives in your terminal and has a questionable emotional backstory.

I built this as a learning project to understand how coding agents like Claude Code actually work under the hood.
Instead of just reading about tool calling, agent loops, context management and filesystem interaction, I decided to build a small version myself.
It's not Claude Code or Curson
It's not trying to replace them.
It's a small-scale coding agent that I built to fuck around with agent architecture and actually understand what is happening.
And yes, it has a mascot.
What can it do?
The agent currently has access to the following tools:
Tool	What it does
read_file	Reads file contents
list_files	Lists files and directories
glob_files	Finds files using patterns
grep_search	Searches through the codebase using regex
edit_file	Creates or edits files
multi_edit	Performs multiple edits to a file
run_command	Executes terminal commands with user confirmation
todo_write	Maintains a task/todo list


So instead of simply asking an LLM:
"how do I fix this?"
the model can actually inspect the codebase, search for relevant code, make edits, run commands when approved, and keep track of multi-step work.
How it works
At a high level, the architecture is:
User
  │
  ▼
CLI Interface
  │
  ▼
Gemini Chat Session
  │
  ├── System Prompt
  │
  ├── Tool Definitions
  │      ├── read_file
  │      ├── list_files
  │      ├── glob_files
  │      ├── grep_search
  │      ├── edit_file
  │      ├── multi_edit
  │      ├── run_command
  │      └── todo_write
  │
  ▼
Gemini Tool Calling
  │
  ▼
Tool Execution
  │
  ▼
Result returned to model
  │
  ▼
Final response streamed to CLI
The agent uses Google's genai Python SDK and creates a persistent chat session with the model and its available tools.
The model can make up to 30 automatic remote tool calls during a conversation.
Technical Details
Model
The current model configured in the agent is:
MODEL = "gemini-3.5-flash-lite"
The Gemini client is initialized using the GEMINI_API_KEY environment variable or an API key passed through the CLI.
Core stack
- Python
- Google GenAI SDK
- Pydantic
- python-dotenv
- uv for dependency and environment management
Agent architecture
The main agent is implemented in agent.py.
The AIAgent class is responsible for:
- Creating the Gemini client
- Creating the chat session
- Registering the available tools
- Maintaining the todo state
- Streaming model responses
- Handling tool execution
Tool functions are registered directly with the Gemini generation configuration:
tools=[
    self.read_file,
    self.list_files,
    self.edit_file,
    self.multi_edit,
    self.glob_files,
    self.grep_search,
    self.run_command,
    self.todo_write,
]
This lets the model decide when a tool is useful instead of requiring a manually coded routing layer.
Tool Implementation
File reading
read_file reads a file using UTF-8 encoding and returns its contents to the model.
Directory listing
list_files recursively isn't used here; it lists the contents of a requested directory and labels entries as files or directories.
Glob search
glob_files uses Python's pathlib glob functionality to find matching files.
The agent skips directories such as:
.git
node_modules
.venv
venv
__pycache__
.idea
.mypy_cache
Code search
grep_search uses Python regular expressions to search through files.
It supports:
- Regex patterns
- Case-sensitive or case-insensitive search
- File glob filtering
- Up to 200 returned matches
Editing
edit_file can either create a new file or replace an existing section of a file.
The editing logic checks that:
- The requested old text exists
- Ambiguous matches aren't replaced accidentally
- replace_all is explicitly requested when necessary
Multi-edit
multi_edit applies multiple edits to the same file.
If an edit fails, the operation returns an error before writing the resulting content.
Command execution
run_command allows the model to request terminal commands, but the user must explicitly approve them:
Run this command? [y/N]:
Command output is captured and returned to the model.
Output is also truncated at 8000 characters to prevent huge command results from flooding the context.
Todo management
todo_write maintains an in-memory task list with:
[ ] pending
[~] in_progress
[x] completed
This gives the model a lightweight way to break larger coding tasks into explicit steps.
Context & Safety
The agent's system prompt defines how it should behave while working on a codebase.
Some important constraints include:
- Defensive security assistance only
- Never expose or commit secrets
- Follow existing project conventions
- Inspect existing code before modifying it
- Avoid unnecessary comments
- Use the available tools instead of pretending to have performed actions
- Ask for confirmation before executing terminal commands
The project also loads environment variables with python-dotenv, keeping API credentials outside the source code.
Project Structure
.
├── agent.py
├── inventory_tracker.py
├── test_inventory.py
├── ascii-art.txt
├── pyproject.toml
├── uv.lock
└── README.md
Generated/local files such as .env, agent.log, and __pycache__/ should remain untracked.
Setup
1. Clone the repository
git clone <your-repository-url>
cd <your-repository>
2. Install dependencies
This project uses uv.
uv sync
3. Configure your API key
Create a .env file:
GEMINI_API_KEY=your_api_key_here
Do not commit .env.
Run the Agent
Start the coding agent with:
uv run agent.py
You can also provide the API key directly:
uv run agent.py --api-key YOUR_API_KEY
Once started, the agent loads the ASCII mascot and opens an interactive terminal session.
You: inspect the project and explain how the inventory system works
The agent can then use its tools to inspect the codebase and respond.
Type:
exit
or:
quit
to end the session.
Why I Built This
The goal wasn't to build another production-ready coding assistant.
The goal was to understand the mechanics behind agentic coding systems by actually implementing one.
This project helped me get hands-on with:
- LLM tool calling
- Agent loops
- Function calling
- Context management
- Filesystem interaction
- Code search
- Automated editing
- Human-in-the-loop command execution
- Task planning
- Streaming model responses
- CLI application architecture
Building even a small version makes the architecture behind tools like Claude Code much less mysterious.
Current Limitations
This is intentionally a small learning project.
Some current limitations include:
- No persistent conversation memory between runs
- Todo state is in-memory only
- No sophisticated codebase indexing
- No embeddings/vector database
- No parallel tool execution layer
- No sophisticated patch/diff system
- No production-grade sandboxing
- No web browsing tool
- No multi-agent architecture
- No persistent agent state
Those are potential directions for future iterations.
Future Ideas
Some things I'd like to experiment with next:
- Better context management
- Smarter codebase indexing
- Git-aware tooling
- Diff previews before edits
- Persistent conversation history
- More robust command sandboxing
- Parallel tool execution
- Sub-agents
- MCP integration
- Better terminal UX
- Streaming tool status
- Agent evaluation and benchmarking
Disclaimer
This is an educational project inspired by the architecture of modern coding agents.
It is intentionally small, imperfect, and built primarily for learning.
The point isn't to recreate Claude Code.
The point is to understand what makes an agent an agent.
