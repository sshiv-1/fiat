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
