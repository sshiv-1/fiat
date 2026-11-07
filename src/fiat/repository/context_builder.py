"""Token-budgeted repository context retrieval for Fiat's planning agent."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fiat.repository.import_graph import ImportGraph
from fiat.repository.scanner import (
    ProjectInstruction,
    RepositoryScanner,
    RepositorySnapshot,
)
from fiat.repository.search import RepositorySearch, SearchMatch
from fiat.repository.symbol_index import Symbol, SymbolIndex
from fiat.tools.workspace import WorkspaceManager

_STOP_WORDS = {
    "about",
    "after",
    "agent",
    "and",
    "code",
    "create",
    "file",
    "fix",
    "for",
    "from",
    "implement",
    "into",
    "make",
    "please",
    "project",
    "repository",
    "that",
    "the",
    "this",
    "with",
}


@dataclass(frozen=True)
class ContextSnippet:
    """A bounded source excerpt chosen for a task."""

    path: str
    start_line: int
    end_line: int
    content: str
    reason: str
    score: int


@dataclass
class RepositoryContext:
    """Structured, auditable context sent to planning without whole-repo dumping."""

    task: str
    snapshot: RepositorySnapshot
    snippets: list[ContextSnippet] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    instructions: list[ProjectInstruction] = field(default_factory=list)
    estimated_tokens: int = 0
    truncated: bool = False

    def as_prompt(self) -> str:
        """Render the context as compact structured text for a model prompt."""
        lines = [
            f"Project root: {self.snapshot.root}",
            f"Languages: {', '.join(self.snapshot.languages) or 'unknown'}",
            f"Frameworks: {', '.join(self.snapshot.frameworks) or 'none detected'}",
        ]
        if self.instructions:
            lines.append("Instructions (later entries override earlier conflicts):")
            for instruction in self.instructions:
                lines.append(f"[{instruction.path}]\n{instruction.content[:4_000]}")
        if self.symbols:
            lines.append("Relevant symbols:")
            lines.extend(
                f"- {symbol.kind} {symbol.name} ({symbol.path}:{symbol.start_line})"
                for symbol in self.symbols
            )
        if self.snippets:
            lines.append("Relevant source excerpts:")
            for snippet in self.snippets:
                lines.append(
                    f"[{snippet.path}:{snippet.start_line}-{snippet.end_line}; "
                    f"{snippet.reason}]\n{snippet.content}"
                )
        if self.truncated:
            lines.append("Context was truncated to the configured file or token budget.")
        return "\n".join(lines)

    def metadata(self) -> dict[str, object]:
        """Return persistence-safe context metadata without source excerpt contents."""
        return {
            "task": self.task,
            "files": [
                {
                    "path": item.path,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "reason": item.reason,
                    "score": item.score,
                }
                for item in self.snippets
            ],
            "symbols": [asdict(symbol) for symbol in self.symbols],
            "instructions": [item.path for item in self.instructions],
            "estimated_tokens": self.estimated_tokens,
            "truncated": self.truncated,
        }


class ContextBuilder:
    """Ranks narrow repository evidence for one user task."""

    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    def build(
        self,
        task: str,
        *,
        token_budget: int = 3_000,
        max_files: int = 8,
        max_snippets: int = 10,
    ) -> RepositoryContext:
        """Build deduplicated source context while honoring file and token limits."""
        scanner = RepositoryScanner(self.workspace)
        snapshot = scanner.scan()
        symbols = SymbolIndex(snapshot.root).build(snapshot)
        graph = ImportGraph.build(symbols)
        search = RepositorySearch(snapshot, symbols, graph)
        keywords = self._keywords(task)
        file_scores, matches = self._rank_files(snapshot, search, keywords)
        relevant_symbols = self._relevant_symbols(symbols, keywords)
        for symbol in relevant_symbols:
            file_scores[symbol.path] += 6
        self._add_dependency_context(file_scores, graph)
        ranked_paths = [
            path
            for path, _ in sorted(file_scores.items(), key=lambda item: (-item[1], item[0]))
            if _ > 0
        ]
        context = RepositoryContext(
            task=task,
            snapshot=snapshot,
            symbols=relevant_symbols[:20],
            instructions=snapshot.instructions,
        )
        selected_files = 0
        for relative_path in ranked_paths:
            if selected_files >= max_files or len(context.snippets) >= max_snippets:
                context.truncated = True
                break
            snippet = self._make_snippet(
                snapshot.root,
                relative_path,
                matches.get(relative_path, []),
                file_scores[relative_path],
                keywords,
                token_budget - context.estimated_tokens,
            )
            if snippet is None:
                context.truncated = True
                continue
            context.snippets.append(snippet)
            context.estimated_tokens += self._estimate_tokens(snippet.content)
            selected_files += 1
        if len(ranked_paths) > selected_files:
            context.truncated = True
        return context

    def save_project_context(self, context: RepositoryContext) -> Path:
        """Save context metadata under `.agent/` without copying source or secrets."""
        directory = context.snapshot.root / ".agent"
        directory.mkdir(exist_ok=True)
        destination = directory / "last-context.json"
        destination.write_text(
            json.dumps(context.metadata(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return destination

    @staticmethod
    def _keywords(task: str) -> list[str]:
        return [
            token.casefold()
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", task)
            if token.casefold() not in _STOP_WORDS
        ]

    def _rank_files(
        self,
        snapshot: RepositorySnapshot,
        search: RepositorySearch,
        keywords: list[str],
    ) -> tuple[dict[str, int], dict[str, list[SearchMatch]]]:
        scores: dict[str, int] = defaultdict(int)
        matches: dict[str, list[SearchMatch]] = defaultdict(list)
        for record in snapshot.files:
            for keyword in keywords:
                if keyword in record.path.casefold():
                    scores[record.path] += 8
        for keyword in keywords[:12]:
            try:
                keyword_matches = search.regex_search(re.escape(keyword), limit=30)
            except ValueError:
                continue
            for match in keyword_matches:
                scores[match.path] += 4
                matches[match.path].append(match)
        return scores, matches

    @staticmethod
    def _relevant_symbols(index: SymbolIndex, keywords: list[str]) -> list[Symbol]:
        scored: list[tuple[int, Symbol]] = []
        for symbol in index.symbols:
            score = sum(
                8 for keyword in keywords if keyword in symbol.name.casefold()
            )
            if score:
                scored.append((score, symbol))
        return [symbol for _, symbol in sorted(scored, key=lambda item: -item[0])]

    @staticmethod
    def _add_dependency_context(scores: dict[str, int], graph: ImportGraph) -> None:
        selected = [path for path, score in scores.items() if score >= 9]
        for path in selected:
            for edge in graph.dependencies(path):
                if edge.target:
                    scores[edge.target] += 2
            for edge in graph.dependents(path):
                scores[edge.source] += 2

    def _make_snippet(
        self,
        root: Path,
        relative_path: str,
        matches: list[SearchMatch],
        score: int,
        keywords: list[str],
        remaining_tokens: int,
    ) -> ContextSnippet | None:
        if remaining_tokens <= 0:
            return None
        try:
            target = self.workspace.validate_path(root / relative_path, operation="context")
            lines = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not lines:
            return None
        line_number = matches[0].line if matches else 1
        start_line = max(1, line_number - 12)
        end_line = min(len(lines), line_number + 24)
        excerpt = "\n".join(lines[start_line - 1 : end_line])
        maximum_characters = max(80, remaining_tokens * 4)
        if len(excerpt) > maximum_characters:
            excerpt = excerpt[:maximum_characters].rsplit("\n", 1)[0] + "\n..."
            end_line = start_line + excerpt.count("\n")
        reason = "text match" if matches else "path or dependency relevance"
        if any(keyword in relative_path.casefold() for keyword in keywords):
            reason = "path match"
        return ContextSnippet(
            path=relative_path,
            start_line=start_line,
            end_line=end_line,
            content=excerpt,
            reason=reason,
            score=score,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)
