"""Filesystem tools that enforce a WorkspaceManager boundary."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fiat.tools.workspace import WorkspaceError, WorkspaceManager


class FileSystemTools:
    """Read and edit files without permitting workspace escapes."""

    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    @staticmethod
    def _apply_edit(content: str, old: str, new: str, replace_all: bool) -> str:
        if not old:
            raise ValueError("old_text is empty")
        count = content.count(old)
        if count == 0:
            raise ValueError(f"text not found: {old[:80]!r}")
        if count > 1 and not replace_all:
            raise ValueError(
                "text appears "
                f"{count} times (add more context or set replace_all): {old[:80]!r}"
            )
        return content.replace(old, new) if replace_all else content.replace(old, new, 1)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_name = temporary_file.name
            os.replace(temporary_name, path)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _format_error(error: Exception) -> str:
        return f"Filesystem error: {error}"

    def read_file(self, path: str) -> str:
        """Read one UTF-8 text file within the workspace."""
        try:
            target = self.workspace.validate_path(path, operation="read")
            if not target.exists():
                return f"File not found: {path}"
            if not target.is_file():
                return f"Path is not a file: {path}"
            return f"File contents of {path}:\n{target.read_text(encoding='utf-8')}"
        except (OSError, UnicodeDecodeError, WorkspaceError) as error:
            return self._format_error(error)

    def list_files(self, path: str = ".") -> str:
        """List one directory without following unsafe symlinks."""
        try:
            target = self.workspace.validate_path(path, operation="list")
            if not target.exists():
                return f"Path not found: {path}"
            if not target.is_dir():
                return f"Path is not a directory: {path}"
            items: list[str] = []
            skipped = 0
            for item in sorted(target.iterdir(), key=lambda entry: entry.name.lower()):
                try:
                    safe_item = self.workspace.validate_path(item, operation="list")
                except WorkspaceError:
                    skipped += 1
                    continue
                marker = "[DIR]  " if safe_item.is_dir() else "[FILE] "
                suffix = "/" if safe_item.is_dir() else ""
                items.append(f"{marker}{item.name}{suffix}")
            if not items:
                return f"Empty directory: {path}"
            result = f"Contents of {path}:\n" + "\n".join(items)
            if skipped:
                result += f"\n({skipped} unsafe entries omitted)"
            return result
        except (OSError, WorkspaceError) as error:
            return self._format_error(error)

    def edit_file(
        self,
        path: str,
        new_text: str,
        old_text: str = "",
        replace_all: bool = False,
    ) -> str:
        """Create a new file or apply a verified replacement atomically."""
        try:
            target = self.workspace.validate_path(path, operation="write")
            if target.exists():
                if not target.is_file():
                    return f"Path is not a file: {path}"
                if not old_text:
                    return (
                        "Refusing to overwrite an existing file without old_text. "
                        "Supply the exact text to replace."
                    )
                content = target.read_text(encoding="utf-8")
                content = self._apply_edit(content, old_text, new_text, replace_all)
                self._atomic_write(target, content)
                return f"Successfully edited {path}"

            if old_text:
                return f"File not found for replacement: {path}"
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(target, new_text)
            return f"Successfully created {path}"
        except (OSError, UnicodeDecodeError, ValueError, WorkspaceError) as error:
            return self._format_error(error)

    def multi_edit(self, path: str, edits: Sequence[Any]) -> str:
        """Apply all replacements to a single file, writing only if all succeed."""
        try:
            target = self.workspace.validate_path(path, operation="write")
            if not target.exists():
                return f"File not found: {path}"
            if not target.is_file():
                return f"Path is not a file: {path}"
            content = target.read_text(encoding="utf-8")
            for index, edit in enumerate(edits, start=1):
                values = self._edit_values(edit)
                try:
                    content = self._apply_edit(
                        content,
                        str(values["old_text"]),
                        str(values["new_text"]),
                        bool(values.get("replace_all", False)),
                    )
                except (KeyError, ValueError) as error:
                    return f"Edit {index} failed; no changes written: {error}"
            self._atomic_write(target, content)
            return f"Successfully applied {len(edits)} edits to {path}"
        except (OSError, UnicodeDecodeError, WorkspaceError) as error:
            return self._format_error(error)

    @staticmethod
    def _edit_values(edit: Any) -> Mapping[str, Any]:
        if isinstance(edit, Mapping):
            return edit
        model_dump = getattr(edit, "model_dump", None)
        if callable(model_dump):
            return model_dump()
        return {
            "old_text": edit.old_text,
            "new_text": edit.new_text,
            "replace_all": getattr(edit, "replace_all", False),
        }

    def glob_files(self, pattern: str, path: str = ".") -> str:
        """Return safe file paths matching a workspace-relative glob."""
        try:
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                return "Filesystem error: Glob patterns cannot escape the workspace."
            base = self.workspace.validate_path(path, operation="glob")
            if not base.exists() or not base.is_dir():
                return f"Path not found: {path}"
            matches: list[Path] = []
            for candidate in base.glob(pattern):
                try:
                    safe_candidate = self.workspace.validate_path(candidate, operation="glob")
                except WorkspaceError:
                    continue
                if safe_candidate.is_file():
                    matches.append(safe_candidate)
            matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
            if not matches:
                return f"No files matched {pattern}"
            return "\n".join(
                item.relative_to(self.workspace.root).as_posix() for item in matches[:200]
            )
        except (OSError, ValueError, WorkspaceError) as error:
            return self._format_error(error)

    def grep_search(
        self,
        pattern: str,
        path: str = ".",
        file_glob: str = "*",
        ignore_case: bool = False,
    ) -> str:
        """Search safe text files using a caller-provided regular expression."""
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as error:
            return f"Invalid regex: {error}"
        try:
            root = self.workspace.validate_path(path, operation="search")
            if not root.exists():
                return f"Path not found: {path}"
            candidates = [root] if root.is_file() else root.rglob(file_glob)
            results: list[str] = []
            for candidate in candidates:
                try:
                    target = self.workspace.validate_path(candidate, operation="search")
                    if not target.is_file():
                        continue
                    with target.open("r", encoding="utf-8") as file_handle:
                        for line_number, line in enumerate(file_handle, start=1):
                            if regex.search(line):
                                relative = target.relative_to(self.workspace.root).as_posix()
                                results.append(
                                    f"{relative}:{line_number}:{line.rstrip()[:200]}"
                                )
                                if len(results) >= 200:
                                    return "\n".join(results) + "\n(truncated at 200 matches)"
                except (OSError, UnicodeDecodeError, WorkspaceError):
                    continue
            return "\n".join(results) if results else f"No matches for {pattern!r}"
        except (OSError, WorkspaceError) as error:
            return self._format_error(error)
