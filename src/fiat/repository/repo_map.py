"""Human-readable repository map rendering and CLI command helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fiat.repository.import_graph import ImportGraph
from fiat.repository.scanner import (
    RepositoryFile,
    RepositoryScanner,
    RepositorySnapshot,
)
from fiat.repository.search import RepositorySearch
from fiat.repository.symbol_index import SymbolIndex
from fiat.tools.workspace import WorkspaceManager


def format_repository_map(snapshot: RepositorySnapshot) -> str:
    """Render actual scanned project metadata as a compact terminal map."""
    lines = [f"Project: {snapshot.root.name or snapshot.root}", "", "Languages:"]
    if snapshot.languages:
        lines.extend(f"- {name} ({count} files)" for name, count in snapshot.languages.items())
    else:
        lines.append("- None detected")
    lines.extend(("", "Frameworks:"))
    lines.extend(f"- {name}" for name in snapshot.frameworks) if snapshot.frameworks else lines.append(
        "- None detected"
    )
    lines.extend(("", "Structure:"))
    lines.extend(_structure_lines(snapshot.files))
    lines.extend(("", "Entry points:"))
    lines.extend(f"- {path}" for path in snapshot.entry_points) if snapshot.entry_points else lines.append(
        "- None detected"
    )
    lines.extend(("", "Detected:"))
    lines.extend(f"- Manifest: {path}" for path in snapshot.manifests) if snapshot.manifests else lines.append(
        "- No known project manifests"
    )
    if snapshot.test_directories:
        lines.extend(f"- Test directory: {path}" for path in snapshot.test_directories)
    if snapshot.instructions:
        lines.append(
            "- Instructions: "
            + " < ".join(item.path for item in snapshot.instructions)
            + " (rightmost wins conflicts)"
        )
    lines.extend(("", "Repository indexing complete."))
    return "\n".join(lines)


def run_repository_command(command: str, arguments: list[str], workspace: WorkspaceManager) -> str:
    """Execute non-interactive repository commands used by both CLI entry points."""
    scanner = RepositoryScanner(workspace)
    snapshot = scanner.scan()
    symbols = SymbolIndex(snapshot.root).build(snapshot)
    graph = ImportGraph.build(symbols)
    search = RepositorySearch(snapshot, symbols, graph)
    normalized = command.casefold()
    if normalized == "/index":
        destination = scanner.save_index(snapshot)
        return f"{format_repository_map(snapshot)}\nIndex metadata: {destination.relative_to(snapshot.root)}"
    if normalized == "/map":
        return format_repository_map(snapshot)
    if normalized == "/search":
        query = " ".join(arguments).strip()
        if not query:
            return "Usage: fiat /search <query>"
        try:
            search_matches = search.regex_search(query)
        except ValueError as error:
            return str(error)
        if not search_matches:
            return f"No matches for {query!r}."
        return "\n".join(
            f"{item.path}:{item.line}:{item.text}" for item in search_matches
        )
    if normalized == "/symbol":
        query = " ".join(arguments).strip()
        if not query:
            return "Usage: fiat /symbol <name>"
        symbol_matches = search.symbol_search(query)
        if not symbol_matches:
            return f"No symbols found for {query!r}."
        return "\n".join(
            f"{item.kind} {item.name} {item.path}:{item.start_line}-{item.end_line}"
            for item in symbol_matches
        )
    return f"Unknown repository command: {command}"


def _structure_lines(files: Sequence[RepositoryFile], limit: int = 80) -> list[str]:
    paths = sorted(Path(file.path) for file in files)
    if not paths:
        return ["(no indexed files)"]
    lines: list[str] = []
    seen_directories: set[Path] = set()
    for path in paths[:limit]:
        for depth in range(1, len(path.parts)):
            directory = Path(*path.parts[:depth])
            if directory not in seen_directories:
                lines.append(f"{'  ' * (depth - 1)}{directory.name}/")
                seen_directories.add(directory)
        lines.append(f"{'  ' * (len(path.parts) - 1)}{path.name}")
    if len(paths) > limit:
        lines.append(f"… {len(paths) - limit} additional indexed files")
    return lines
