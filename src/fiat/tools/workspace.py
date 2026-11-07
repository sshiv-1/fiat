"""Workspace-rooted path validation for local agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(ValueError):
    """Raised when an operation would escape or expose the workspace."""


_SENSITIVE_FILENAMES = {
    "credentials",
    "credentials.json",
    "credentials.yaml",
    "credentials.yml",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
}
_SAFE_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
_SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


@dataclass(frozen=True)
class WorkspaceManager:
    """Resolves tool paths beneath one explicit, canonical project root."""

    root: Path

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root).expanduser().resolve())
        if not self.root.is_dir():
            raise WorkspaceError(f"Workspace root is not a directory: {self.root}")

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve a path and reject traversal or symlink escapes."""
        supplied = Path(path).expanduser()
        candidate = supplied if supplied.is_absolute() else self.root / supplied
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise WorkspaceError(
                f"Rejected path outside workspace root: {path}"
            ) from error
        return resolved

    def validate_path(
        self,
        path: str | Path,
        *,
        operation: str,
        allow_sensitive: bool = False,
    ) -> Path:
        """Resolve a path and reject sensitive workspace files by default."""
        resolved = self.resolve_path(path)
        relative = resolved.relative_to(self.root)
        if not allow_sensitive and self.is_sensitive(relative):
            raise WorkspaceError(
                f"Rejected {operation} for protected file: {relative.as_posix()}"
            )
        return resolved

    @staticmethod
    def is_sensitive(relative_path: Path) -> bool:
        """Return whether a workspace-relative path commonly holds a secret."""
        parts = tuple(part.lower() for part in relative_path.parts)
        if parts and parts[0] == ".fiat":
            return True
        if any(part in {".ssh", ".aws", ".gnupg"} for part in parts):
            return True
        name = relative_path.name.lower()
        if name in _SAFE_ENV_EXAMPLES:
            return False
        if name == ".env" or name.startswith(".env."):
            return True
        if (
            name in _SENSITIVE_FILENAMES
            or name.endswith(".credentials")
            or name.startswith(("credential", "secret"))
        ):
            return True
        return relative_path.suffix.lower() in _SENSITIVE_SUFFIXES

    def relative_path(self, path: str | Path) -> Path:
        """Return a validated workspace-relative path."""
        return self.resolve_path(path).relative_to(self.root)
