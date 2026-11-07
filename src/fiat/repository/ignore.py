"""Minimal gitignore-aware filtering with Fiat's hard safety exclusions."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".agent",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "vendor",
        "venv",
    }
)


@dataclass(frozen=True)
class IgnoreRule:
    """One parsed ignore rule, retaining whether it negates an earlier match."""

    pattern: str
    negated: bool = False
    directory_only: bool = False


class GitIgnoreMatcher:
    """Applies a practical subset of gitignore rules during repository discovery."""

    def __init__(
        self,
        root: Path,
        excluded_directories: set[str] | None = None,
    ) -> None:
        self.root = root
        self.excluded_directories = DEFAULT_EXCLUDED_DIRECTORIES | frozenset(
            excluded_directories or set()
        )
        self.rules = self._read_rules(root / ".gitignore")

    @staticmethod
    def _read_rules(path: Path) -> tuple[IgnoreRule, ...]:
        if not path.is_file():
            return ()
        rules: list[IgnoreRule] = []
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            pattern = line[1:] if negated else line
            if not pattern:
                continue
            rules.append(
                IgnoreRule(
                    pattern=pattern.rstrip("/"),
                    negated=negated,
                    directory_only=pattern.endswith("/"),
                )
            )
        return tuple(rules)

    def is_ignored(self, relative_path: Path, is_directory: bool = False) -> bool:
        """Return whether a workspace-relative path should not be indexed."""
        if any(part in self.excluded_directories for part in relative_path.parts):
            return True
        ignored = False
        for rule in self.rules:
            if rule.directory_only and not is_directory:
                continue
            if self._matches(relative_path, rule.pattern):
                ignored = not rule.negated
        return ignored

    @staticmethod
    def _matches(relative_path: Path, pattern: str) -> bool:
        normalized = relative_path.as_posix()
        if pattern.startswith("/"):
            return fnmatch.fnmatchcase(normalized, pattern[1:])
        if "/" in pattern:
            return fnmatch.fnmatchcase(normalized, pattern) or fnmatch.fnmatchcase(
                normalized, f"**/{pattern}"
            )
        return any(fnmatch.fnmatchcase(part, pattern) for part in relative_path.parts)
