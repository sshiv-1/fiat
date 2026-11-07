"""Repository search with ripgrep acceleration and a deterministic Python fallback."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass

from fiat.repository.import_graph import DependencyEdge, ImportGraph
from fiat.repository.scanner import RepositorySnapshot
from fiat.repository.symbol_index import Symbol, SymbolIndex


@dataclass(frozen=True)
class SearchMatch:
    """A text-search result with a workspace-relative source location."""

    path: str
    line: int
    text: str


class RepositorySearch:
    """Provides file, regex, symbol, and dependency queries over an index."""

    def __init__(
        self,
        snapshot: RepositorySnapshot,
        symbols: SymbolIndex,
        graph: ImportGraph,
    ) -> None:
        self.snapshot = snapshot
        self.symbols = symbols
        self.graph = graph
        self._allowed_paths = {file.path for file in snapshot.files}

    def file_search(self, query: str, limit: int = 50) -> list[str]:
        """Find indexed files whose path contains a case-insensitive query."""
        normalized = query.casefold()
        return [
            file.path
            for file in self.snapshot.files
            if normalized in file.path.casefold()
        ][:limit]

    def regex_search(self, pattern: str, limit: int = 100) -> list[SearchMatch]:
        """Search indexed content, preferring ripgrep where it is installed."""
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"Invalid regex: {error}") from error
        if shutil.which("rg"):
            matches = self._ripgrep_search(pattern, limit)
            if matches is not None:
                return matches
        return self._python_search(pattern, limit)

    def symbol_search(self, query: str) -> list[Symbol]:
        """Look up symbols by name without reading unrelated source files."""
        return self.symbols.lookup(query)

    def dependency_search(self, path: str) -> tuple[list[DependencyEdge], list[DependencyEdge]]:
        """Return direct outgoing dependencies and incoming dependents for a file."""
        return self.graph.dependencies(path), self.graph.dependents(path)

    def _ripgrep_search(self, pattern: str, limit: int) -> list[SearchMatch] | None:
        try:
            process = subprocess.run(
                ["rg", "--json", "--line-number", "--color", "never", "-e", pattern],
                cwd=self.snapshot.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if process.returncode not in {0, 1}:
            return None
        matches: list[SearchMatch] = []
        for raw_line in process.stdout.splitlines():
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "match":
                continue
            data = payload.get("data", {})
            relative = data.get("path", {}).get("text")
            line_number = data.get("line_number")
            text = data.get("lines", {}).get("text", "").rstrip()
            if (
                isinstance(relative, str)
                and isinstance(line_number, int)
                and relative.replace("\\", "/") in self._allowed_paths
            ):
                matches.append(
                    SearchMatch(relative.replace("\\", "/"), line_number, text)
                )
                if len(matches) >= limit:
                    break
        return matches

    def _python_search(self, pattern: str, limit: int) -> list[SearchMatch]:
        regex = re.compile(pattern)
        matches: list[SearchMatch] = []
        for relative in sorted(self._allowed_paths):
            path = self.snapshot.root / relative
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if regex.search(line):
                            matches.append(SearchMatch(relative, line_number, line.rstrip()))
                            if len(matches) >= limit:
                                return matches
            except (OSError, UnicodeDecodeError):
                continue
        return matches
