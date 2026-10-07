# Fiat

> A provider‑agnostic, multi‑agent coding assistant that runs directly from your terminal.

Fiat is a Python‑based coding agent designed to work like a lightweight AI‑powered development environment directly in your terminal. It supports multiple LLM providers, interactive provider/model switching, tool‑based repository interaction, live context/token monitoring, and an iterative multi‑agent workflow that can **plan → implement → test → review → fix** code.

---

## ✨ Features
- 🤖 **Multi‑agent coding workflow** (Planner → Coder → Tester → Reviewer)
- 🔌 **Multiple LLM providers** (Gemini, OpenAI, Anthropic, OpenRouter, Groq)
- 🔄 **Runtime provider and model switching** via slash commands
- 🔁 **Automatic iteration** when tests or review fail
- 🛠️ **Tool‑based repository interaction** (read, edit, run commands, etc.)
- 🔐 **Command confirmation and execution safety**
- 📊 **Interactive `/context` dashboard** with token usage and cost tracking
- 💬 **Interactive terminal UI** with arrow‑key navigation
- ⌨️ **Slash‑command autocomplete**
- 📦 **Installable as a global CLI** (`fiat` command)
- 🚀 **Works outside the development repository**
- ⚙️ **Configurable maximum agent iterations** (default 3)
- 🌊 **Streaming model responses**
- 💰 **Token usage and estimated cost tracking**

---

# 🧠 What is Fiat?
Fiat is a terminal‑native AI coding agent. Instead of manually switching between an LLM, your editor, shell, tests, and code review, Fiat coordinates these tasks through a single CLI.

A simple request can be handled directly. A complex coding task automatically goes through:

```text
User Request
   │
   ▼
Orchestrator
   │
   ▼
Planner → Coder → Tester → Reviewer
   └───────────────┐
                 │
               APPROVED
                 │
                DONE
```

This allows Fiat to iteratively improve an implementation instead of stopping after the first generation.

---

## 🚀 Installation
### Requirements
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

### Install from the repository
```bash
# Clone the repo
git clone https://github.com/sshiv-1/fiat.git
cd fiat

# Install as a global CLI
uv tool install .
```
You can now run the command from **any** directory:
```bash
fiat
```

### Development installation
For development you can run Fiat directly from the source tree:
```bash
uv run python -m fiat
```
The development launcher (`agent.py`) is still available for quick iteration.

---

## 💻 Running Fiat
```bash
fiat
```
You will be dropped into an interactive prompt. Example interaction:
```
You: Add authentication to this FastAPI application.
```
- Simple requests are answered directly.
- Complex coding tasks invoke the full multi‑agent workflow automatically.

---

## 🔌 Supported Providers
Fiat abstracts providers so the core does not depend on a single LLM.
Currently supported providers:
- **Google Gemini**
- **OpenAI**
- **Anthropic**
- **OpenRouter**
- **Groq**

The provider layer handles authentication, model selection, streaming, tool/function calling, and token usage metadata. Adding a new provider only requires implementing the common `Provider` interface.

---

## 🔄 Provider and Model Switching
Switch providers or models at runtime using the interactive slash commands:
- `/provider` – choose a provider
- `/model` – choose a model

Both commands use arrow‑key navigation rather than numeric menus.

---

## 🔐 Authentication
Configure or re‑enter API keys with:
```
/auth
```
Credentials are stored securely under `~/.fiat/`. No external backend is required.

---

## ⌨️ CLI Commands
| Command | Description |
|--------|-------------|
| `/provider` | Change the active LLM provider |
| `/model` | Change the active model |
| `/auth` | Configure or re‑enter authentication |
| `/context` | Open the interactive context and usage dashboard |
| `/help` | Show available commands |
| `/exit` | Exit Fiat |
| `/quit` | Exit Fiat |

Slash‑command recommendations appear while you type, e.g. typing `/mo` displays `/model`.

---

## 📊 Interactive `/context` Dashboard
Run `/context` to open a full‑screen TUI showing:
- Provider & model
- Context window size and usage
- Token counts (input, output, tool)
- Estimated cost
- Session statistics (requests, iterations)
- Agent status, current role, iteration number

Navigation:
- `↑/↓` – move between sections
- `Enter` – expand/collapse a section
- `Esc` or `q` – close the dashboard

If metadata is unavailable, “Unavailable” is displayed instead of fabricated values.

---

## 🤖 Multi‑Agent Architecture
Fiat’s multi‑agent system builds on the existing provider, CLI, tool, and UI layers.

### Orchestrator
Coordinates the workflow, decides whether a request is simple or complex, initializes specialist agents, maintains shared state, enforces iteration limits, and decides when the task is complete.

### Planner
*Read‑only* specialist that inspects the repository and produces a concrete implementation plan.
- **Tools:** `read_file`, `list_files`, `glob_files`, `grep_search`
- **Cannot:** edit files or run commands.

### Coder
Implements the plan, creates/edits files, runs commands, and responds to feedback.
- **Tools:** `read_file`, `list_files`, `glob_files`, `grep_search`, `edit_file`, `multi_edit`, `run_command`

### Tester
Executes tests/validation commands.
- **Tools:** `run_command`
- Returns `PASS`, `FAIL`, or `NO_TESTS` with details.

### Reviewer
Read‑only specialist that checks the final implementation against the plan and requirements.
- **Tools:** `read_file`, `list_files`, `glob_files`, `grep_search`
- Returns `APPROVED` or `REJECTED` with findings.

### Iteration Loop
```
Planner → Coder → Tester → Reviewer
   ▲            │            ▼
   └─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←─←
```
- If the Tester fails → back to Coder.
- If the Reviewer rejects → back to Coder.
- Loop continues until approval, success, or the **maximum iteration count** is reached.

---

## 🔢 Maximum Agent Iterations
To avoid endless loops, Fiat stops after a configurable number of iterations (default **3**).
Configure via environment variable:
```bash
export FIAT_MAX_AGENT_ITERATIONS=5
```
When the limit is hit Fiat prints a clear warning and returns the partial result.

---

## 🛡️ Safety Model
Each specialist receives only the tools it needs:
- **Planner:** READ‑ONLY tools
- **Coder:** READ, WRITE, EXECUTE tools
- **Tester:** EXECUTE only (`run_command`)
- **Reviewer:** READ‑ONLY tools

All commands that modify the system still go through Fiat’s existing **command‑confirmation** prompt, e.g.
```
Run this command? [Y/n]:
```
No hidden privileged paths exist.

---

## 🧩 Shared Runtime State
A central `AgentWorkflowState` (exposed via `fiat.state.session_state`) tracks:
- `provider`, `model`
- `context_window`, token counters, `estimated_cost`
- `requests`, `current_role`, `current_iteration`, `max_iterations`
- `plan`, `test_results`, `review_findings`

The `/context` UI and the orchestration layer read from this single source of truth.

---

## 🏗️ Project Structure
```
fiat/
├── src/
│   └── fiat/
│       ├── agents/
│       │   ├── __init__.py
│       │   └── orchestrator.py
│       ├── providers/
│       │   ├── provider_gemini.py
│       │   ├── provider_openai.py
│       │   ├── provider_anthropic.py
│       │   └── ...
│       ├── cli.py
│       ├── config.py
│       ├── context_ui.py
│       ├── state.py
│       ├── ui.py
│       ├── __init__.py
│       └── __main__.py
├── tests/
│   ├── test_providers.py
│   └── test_agents.py
├── README.md
├── pyproject.toml
└── uv.lock
```
The layout follows a modern *src* layout and can evolve as new modules are added.

---

## ⚙️ Architecture Overview
```
User → CLI → Orchestrator
   │                     ├─ Planner (read‑only)
   │                     ├─ Coder (read/write/exec)
   │                     ├─ Tester (exec)
   │                     └─ Reviewer (read‑only)
   │
   ▼
Session State ↔ Context UI
```
Providers sit beneath the agents via `ProviderFactory`.

---

## 📦 Packaging
The package defines a console script entry point:
```toml
[project.scripts]
fiat = "fiat.cli:main"
```
Build with:
```bash
uv build
```

---

## 🧪 Testing
Run the full test suite:
```bash
pytest
```
Key test coverage areas:
- Provider behavior and token tracking
- Orchestrator workflow and iteration limits
- Tool‑permission enforcement per specialist
- State updates and UI integration

---

## 🛠️ Development
```bash
# Clone and sync dependencies
git clone https://github.com/sshiv-1/fiat.git
cd fiat
uv sync

# Run fiat from source
uv run python -m fiat

# Run the test suite
pytest

# Build the distributable
uv build
```
Contributions are welcome – see the **Contributing** section below.

---

## 🌍 Why Fiat?
Typical LLM coding workflows require manual coordination:
```
LLM → Editor → Shell → Tests → LLM → Review
```
Fiat consolidates this into a single controlled loop, keeping the developer in the driver’s seat while the agent handles repetitive reasoning and iteration.

---

## 🚧 Current Limitations
- No parallel specialist execution (sequential only).
- Provider metadata may vary in granularity.
- Malformed tool‑call output can abort an iteration.
- Focused on local terminal use; no web UI or remote backend.

---

## 🗺️ Roadmap
- Parallel task decomposition
- Better recovery from malformed tool calls
- Enhanced workflow visualisation
- Additional provider integrations
- More sophisticated planning & dependency management
- Expanded observability and logging

---

## 🤝 Contributing
We welcome bug reports, feature ideas, and pull requests.
When contributing, please:
- Keep provider abstractions intact.
- Preserve the explicit tool‑permission model.
- Maintain the command‑confirmation safety flow.
- Add tests for any new behavior.
- Document changes in the README and inline docstrings.

---

## 📄 License
FIAT is released under the [MIT License](LICENSE). See the [LICENSE](LICENSE) file for details.

---

# ⭐ Fiat
Give an AI coding agent the tools to **understand**, **build**, **test**, **review**, and **improve** software — while keeping the developer in control.
