"""Best-effort local import graph construction for indexed repositories."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from fiat.repository.symbol_index import ImportReference, SymbolIndex


@dataclass(frozen=True)
class DependencyEdge:
    """An import from one file to a resolved or unresolved dependency."""

    source: str
    specifier: str
    target: str | None
    line: int


@dataclass
class ImportGraph:
    """Directed local dependency graph; external imports stay explicitly unresolved."""

    root: Path
    edges: dict[str, list[DependencyEdge]] = field(default_factory=dict)

    @classmethod
    def build(cls, index: SymbolIndex) -> ImportGraph:
        """Build a graph from a language-agnostic symbol index."""
        graph = cls(root=index.root)
        grouped: dict[str, list[DependencyEdge]] = defaultdict(list)
        known_paths = index.indexed_files
        for reference in index.imports:
            target = graph._resolve(reference, known_paths)
            grouped[reference.path].append(
                DependencyEdge(
                    source=reference.path,
                    specifier=reference.specifier,
                    target=target,
                    line=reference.line,
                )
            )
        graph.edges = dict(grouped)
        return graph

    def dependencies(self, path: str) -> list[DependencyEdge]:
        """Return direct outgoing dependencies for a file."""
        return list(self.edges.get(path, []))

    def dependents(self, path: str) -> list[DependencyEdge]:
        """Return all direct edges that resolve to a requested file."""
        return [
            edge
            for edges in self.edges.values()
            for edge in edges
            if edge.target == path
        ]

    def unresolved(self) -> list[DependencyEdge]:
        """Return imports that could not be proven local to the repository."""
        return [
            edge for edges in self.edges.values() for edge in edges if edge.target is None
        ]

    def _resolve(self, reference: ImportReference, known_paths: set[str]) -> str | None:
        if reference.language == "Python":
            candidates = self._python_candidates(reference)
        else:
            candidates = self._javascript_candidates(reference)
        for candidate in candidates:
            normalized = candidate.as_posix()
            if normalized in known_paths:
                return normalized
        return None

    def _python_candidates(self, reference: ImportReference) -> list[Path]:
        source_parent = Path(reference.path).parent
        if reference.level:
            base = source_parent
            for _ in range(reference.level - 1):
                base = base.parent
        else:
            base = Path()
        module_path = Path(*filter(None, reference.specifier.split(".")))
        bases = [base / module_path] if reference.specifier else [base]
        if not reference.level and reference.specifier:
            bases.append(source_parent / module_path)
        candidates: list[Path] = []
        for item in bases:
            candidates.append(item.with_suffix(".py"))
            for imported_name in reference.names:
                candidates.append(item / f"{imported_name}.py")
            candidates.append(item / "__init__.py")
        return candidates

    def _javascript_candidates(self, reference: ImportReference) -> list[Path]:
        if not reference.specifier.startswith("."):
            return []
        base = Path(reference.path).parent / reference.specifier
        candidates = [base]
        for extension in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
            candidates.append(base.with_suffix(extension))
        for extension in (".js", ".jsx", ".ts", ".tsx"):
            candidates.append(base / f"index{extension}")
        return candidates
