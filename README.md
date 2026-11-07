# Fiat

> A provider-agnostic, multi-agent AI coding assistant that runs directly from your terminal.

[![PyPI](https://img.shields.io/pypi/v/fiat-pup.svg)](https://pypi.org/project/fiat-pup/)
[![Python](https://img.shields.io/pypi/pyversions/fiat-pup.svg)](https://pypi.org/project/fiat-pup/)

Fiat is a Python-based coding agent designed to work like a lightweight AI-powered development environment directly in your terminal. It supports multiple LLM providers, interactive provider/model switching, tool-based repository interaction, live context/token monitoring, and an iterative multi-agent workflow that can **plan → implement → test → review → fix** code.

**PyPI package:** [`fiat-pup`](https://pypi.org/project/fiat-pup/)  
**CLI command:** `fiat`

---

## ✨ Features

- 🤖 **Multi-agent coding workflow** (Planner → Coder → Tester → Reviewer)
- 🔌 **Multiple LLM providers** (Gemini, OpenAI, Anthropic, OpenRouter, Groq)
- 🔄 **Runtime provider and model switching** via slash commands
- 🔁 **Automatic iteration** when tests or review fail
- 🛠️ **Tool-based repository interaction** (read, edit, run commands, etc.)
- 🔐 **Command confirmation and execution safety**
- 📊 **Interactive `/context` dashboard** with token usage and cost tracking
- 💬 **Interactive terminal UI** with arrow-key navigation
- ⌨️ **Slash-command autocomplete**
- 📦 **Installable from PyPI** as a global CLI (`fiat` command)
- 🚀 **Works outside the development repository**
- ⚙️ **Configurable maximum agent iterations** (default 3)
- 🌊 **Streaming model responses**
- 💰 **Token usage and estimated cost tracking**

---

# 🧠 What is Fiat?

Fiat is a terminal-native AI coding agent. Instead of manually switching between an LLM, your editor, shell, tests, and code review, Fiat coordinates these tasks through a single CLI.

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

## Repository intelligence and safer local tools

Fiat indexes the current workspace before multi-agent coding workflows. It
uses bounded, `.gitignore`-aware discovery, Python AST symbols, lightweight
JavaScript/TypeScript extraction, local import relationships, and token-budgeted
context snippets. No embeddings or external repository services are required.

Run these commands without configuring an LLM provider:

```bash
fiat /index
fiat /map
fiat /search collision
fiat /symbol collision_detector
```

`/index` writes metadata only to `.agent/repository-index.json`, which is
ignored by Git. Project instructions are loaded in precedence order
`CLAUDE.md < AGENTS.md < FIAT.md`; later files win when instructions conflict.

Filesystem tools are confined to the selected workspace and reject traversal,
symlink escapes, and common credential files. Commands run without a shell,
have time/output limits, and require explicit approval unless classified
read-only. See [SECURITY.md](SECURITY.md) for the remaining limitations.

## Phase 2: structured Plan Mode and permissions

Fiat now has two interaction modes. The active mode is visible in the prompt,
and **Shift+Tab** toggles it immediately without restarting Fiat or clearing
the current conversation. Prompt-toolkit maps the common Windows and Linux
BackTab sequences; if a terminal does not expose Shift+Tab, use the command
fallback instead.

```text
/mode
/mode plan
/mode work
```

**Plan Mode** turns a coding request into a dependency-aware implementation
plan. It builds bounded repository context through the existing repository
intelligence, gives the model only read-only tools, validates the returned
Pydantic data, and displays every task before asking for a decision. It never
edits a source file, runs a command, installs a dependency, or begins plan
execution. The only Plan Mode writes are Fiat's own local plan metadata under
`.fiat/`, which is ignored by Git.

Each persisted plan includes a stable plan ID, schema version, timestamps,
revision number, lifecycle state, and typed tasks. Tasks have stable IDs,
dependencies, target files, and measurable acceptance criteria. Fiat rejects
duplicate IDs, missing/self dependencies, cycles, empty tasks, unsupported
schemas, and invalid lifecycle transitions. Valid tasks are displayed in a
deterministic topological order.

```text
Plan > Add JWT authentication
IMPLEMENTATION PLAN
Plan: Add JWT authentication
ID: plan_...
Status: AWAITING_APPROVAL

TASK 01 [task_schemas] — Define authentication schemas
Dependencies: None
Targets: src/auth/schemas.py
Acceptance criteria:
  - Token request and response schemas validate valid and invalid input.

[A] Approve  [R] Revise  [D] Reject  [C] Cancel
```

Plan controls are available in either mode:

```text
/plan
/plan list
/plan show <id>
/plan approve <id>
/plan reject <id>
/plan revise <id>
/plan cancel <id>
```

`/plan revise <id>` invalidates an existing approval and marks the plan for a
new Plan Mode request. The refreshed plan retains its ID, increments its
revision, must validate again, and needs new explicit approval. Approval only
marks a plan ready for a future executor; it never performs work. `/plan
execute <id>` validates that state and honestly reports that structured
multi-task execution remains a Phase 3 capability.

### Permission architecture

Work Mode keeps Fiat's existing agent workflow, but its exposed file-edit and
non-read-only command boundaries now use one centralized permission manager.
The manager receives the exact operation, command arguments or target path,
working directory, reason, risk level, and operation category before the tool
runs. It supports:

1. Allow once.
2. Allow this exact operation for the current session.
3. Allow this exact non-destructive operation for this workspace.
4. Deny.

Workspace grants are exact fingerprints, including command arguments and
target resource; there are no wildcard, global-shell, or unrestricted
workspace grants. Destructive commands always require a new one-time decision.
Git pushes also require explicit approval each time. Permissions and audit
events live separately from plans in `.fiat/permissions.json` and
`.fiat/permission-audit.json`; session grants remain in memory only.

Approval is deliberately not a sandbox escape hatch. Fiat still validates
workspace containment, symlink escapes, protected files, command parsing,
shell-free execution, time/output limits, and environment protection after a
user grants permission. If prompting, grant loading, or authorization fails,
the sensitive operation is denied.

Phase 2 does not add an autonomous plan executor. Work Mode can still use the
existing Phase 1 implementation workflow with permissions, while approved
structured plans are durable handoff artifacts for Phase 3.

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
