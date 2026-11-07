"""Bounded, ignore-aware repository discovery."""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fiat.repository.file_classifier import (
    FileCategory,
    classify_file,
    is_binary_prefix,
    language_for_path,
)
from fiat.repository.ignore import GitIgnoreMatcher
from fiat.tools.workspace import WorkspaceManager

PROJECT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "setup.py",
)
INSTRUCTION_PRECEDENCE = ("CLAUDE.md", "AGENTS.md", "FIAT.md")


@dataclass(frozen=True)
class RepositoryFile:
    """Metadata retained for one safe, text-based repository file."""

    path: str
    category: FileCategory
    language: str | None
    size: int


@dataclass(frozen=True)
class ProjectInstruction:
    """A supported instruction file and its documented precedence order."""

    path: str
    precedence: int
    content: str


@dataclass
class RepositorySnapshot:
    """A bounded view of repository metadata with no source file contents."""

    root: Path
    files: list[RepositoryFile] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    test_directories: list[str] = field(default_factory=list)
    instructions: list[ProjectInstruction] = field(default_factory=list)
    cancelled: bool = False
    max_files_reached: bool = False
    skipped_files: int = 0

    def to_dict(self) -> dict[str, object]:
        """Serialize only safe metadata for optional `.agent/` persistence."""
        return {
            "root": str(self.root),
            "files": [
                {**asdict(file), "category": file.category.value} for file in self.files
            ],
            "languages": self.languages,
            "frameworks": self.frameworks,
            "manifests": self.manifests,
            "entry_points": self.entry_points,
            "test_directories": self.test_directories,
            "instructions": [
                {"path": item.path, "precedence": item.precedence}
                for item in self.instructions
            ],
            "cancelled": self.cancelled,
            "max_files_reached": self.max_files_reached,
            "skipped_files": self.skipped_files,
        }


class RepositoryScanner:
    """Scans a project without executing its code or following unsafe links."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        excluded_directories: set[str] | None = None,
        max_file_size: int = 1_000_000,
    ) -> None:
        self.workspace = workspace
        self.excluded_directories = excluded_directories or set()
        self.max_file_size = max_file_size

    def find_project_root(self, start: Path | None = None) -> Path:
        """Find the nearest recognized project root without leaving the workspace."""
        candidate = (start or self.workspace.root).resolve()
        if candidate.is_file():
            candidate = candidate.parent
        while True:
            if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
                return candidate
            if candidate == self.workspace.root or candidate.parent == candidate:
                return self.workspace.root
            candidate = candidate.parent

    def scan(
        self,
        max_files: int = 5_000,
        cancel_check: Callable[[], bool] | None = None,
    ) -> RepositorySnapshot:
        """Discover safe files, manifests, languages, and project conventions."""
        root = self.find_project_root()
        matcher = GitIgnoreMatcher(root, self.excluded_directories)
        snapshot = RepositorySnapshot(root=root)
        languages: Counter[str] = Counter()
        test_directories: set[str] = set()
        for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            if cancel_check and cancel_check():
                snapshot.cancelled = True
                break
            current = Path(directory)
            retained_directories: list[str] = []
            for name in directories:
                child = current / name
                relative_child = child.relative_to(root)
                if (
                    child.is_symlink()
                    or self.workspace.is_sensitive(relative_child)
                    or matcher.is_ignored(relative_child, is_directory=True)
                ):
                    snapshot.skipped_files += 1
                    continue
                retained_directories.append(name)
                if name.lower() in {"test", "tests"}:
                    test_directories.add(relative_child.as_posix())
            directories[:] = retained_directories

            for name in filenames:
                if cancel_check and cancel_check():
                    snapshot.cancelled = True
                    break
                path = current / name
                relative = path.relative_to(root)
                if (
                    path.is_symlink()
                    or self.workspace.is_sensitive(relative)
                    or matcher.is_ignored(relative)
                ):
                    snapshot.skipped_files += 1
                    continue
                if len(snapshot.files) >= max_files:
                    snapshot.max_files_reached = True
                    break
                try:
                    size = path.stat().st_size
                    if size > self.max_file_size:
                        snapshot.skipped_files += 1
                        continue
                    with path.open("rb") as handle:
                        if is_binary_prefix(handle.read(4096)):
                            snapshot.skipped_files += 1
                            continue
                except OSError:
                    snapshot.skipped_files += 1
                    continue
                category = classify_file(relative)
                if category == FileCategory.GENERATED:
                    snapshot.skipped_files += 1
                    continue
                language = language_for_path(relative)
                record = RepositoryFile(
                    path=relative.as_posix(),
                    category=category,
                    language=language,
                    size=size,
                )
                snapshot.files.append(record)
                if language and category in {FileCategory.SOURCE, FileCategory.TEST}:
                    languages[language] += 1
                if category == FileCategory.DEPENDENCY:
                    snapshot.manifests.append(record.path)
            if snapshot.cancelled or snapshot.max_files_reached:
                break

        snapshot.languages = dict(sorted(languages.items()))
        snapshot.test_directories = sorted(test_directories)
        snapshot.frameworks = self._detect_frameworks(root, snapshot.manifests)
        snapshot.entry_points = self._detect_entry_points(snapshot.files)
        snapshot.instructions = self._load_instructions(root)
        return snapshot

    @staticmethod
    def _detect_frameworks(root: Path, manifests: list[str]) -> list[str]:
        indicators = {
            "fastapi": "FastAPI",
            "django": "Django",
            "flask": "Flask",
            "pytest": "pytest",
            "react": "React",
            "next": "Next.js",
            "vue": "Vue",
            "express": "Express",
            "vite": "Vite",
        }
        found: set[str] = set()
        for manifest in manifests:
            try:
                content = (root / manifest).read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for indicator, framework in indicators.items():
                if indicator in content:
                    found.add(framework)
        return sorted(found)

    @staticmethod
    def _detect_entry_points(files: list[RepositoryFile]) -> list[str]:
        entry_names = {
            "__main__.py",
            "app.py",
            "main.py",
            "manage.py",
            "server.py",
            "index.js",
            "index.ts",
            "main.js",
            "main.ts",
            "main.jsx",
            "main.tsx",
        }
        return sorted(
            file.path
            for file in files
            if Path(file.path).name in entry_names
            and file.category in {FileCategory.SOURCE, FileCategory.TEST}
        )

    @staticmethod
    def _load_instructions(root: Path) -> list[ProjectInstruction]:
        instructions: list[ProjectInstruction] = []
        for precedence, name in enumerate(INSTRUCTION_PRECEDENCE, start=1):
            path = root / name
            if not path.is_file() or path.stat().st_size > 100_000:
                continue
            instructions.append(
                ProjectInstruction(
                    path=name,
                    precedence=precedence,
                    content=path.read_text(encoding="utf-8", errors="replace"),
                )
            )
        return instructions

    @staticmethod
    def save_index(snapshot: RepositorySnapshot) -> Path:
        """Save metadata only under an ignored `.agent/` directory."""
        agent_directory = snapshot.root / ".agent"
        agent_directory.mkdir(exist_ok=True)
        destination = agent_directory / "repository-index.json"
        destination.write_text(
            json.dumps(snapshot.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return destination
