"""Language and purpose classification for repository files."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class FileCategory(StrEnum):
    """High-level repository file roles used by indexing and context retrieval."""

    SOURCE = "source"
    TEST = "test"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"
    DEPENDENCY = "dependency"
    BUILD = "build"
    INFRASTRUCTURE = "infrastructure"
    ASSET = "asset"
    GENERATED = "generated"
    UNKNOWN = "unknown"


_LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".dockerfile": "Dockerfile",
}
_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_ASSET_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".mp3",
    ".mp4",
}
_MANIFESTS = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
}


def language_for_path(path: Path) -> str | None:
    """Return a supported language label for a filename, if one is known."""
    if path.name.lower() == "dockerfile":
        return "Dockerfile"
    return _LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def classify_file(path: Path) -> FileCategory:
    """Classify a workspace-relative path without reading its full content."""
    lowered_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    suffix = path.suffix.lower()
    if (
        "generated" in lowered_parts
        or name.endswith(".generated.py")
        or name.endswith(".generated.ts")
        or ".min." in name
    ):
        return FileCategory.GENERATED
    if "tests" in lowered_parts or "test" in lowered_parts or name.startswith("test_"):
        return FileCategory.TEST
    if name.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts")):
        return FileCategory.TEST
    if name in _MANIFESTS:
        return FileCategory.DEPENDENCY
    if name in {"makefile", "dockerfile", "justfile"} or suffix in {".sh", ".ps1"}:
        return FileCategory.BUILD
    if name in {"docker-compose.yml", "docker-compose.yaml"} or any(
        part in {".github", "terraform", "k8s", "helm"} for part in lowered_parts
    ):
        return FileCategory.INFRASTRUCTURE
    if name in {"pyproject.toml", "setup.cfg", "tox.ini", ".gitignore", ".env.example"}:
        return FileCategory.CONFIGURATION
    if suffix in {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"}:
        return FileCategory.CONFIGURATION
    if suffix in {".md", ".rst", ".txt"} or name in {"license", "notice"}:
        return FileCategory.DOCUMENTATION
    if suffix in _SOURCE_SUFFIXES:
        return FileCategory.SOURCE
    if suffix in _ASSET_SUFFIXES:
        return FileCategory.ASSET
    return FileCategory.UNKNOWN


def is_binary_prefix(prefix: bytes) -> bool:
    """Use a conservative binary heuristic without loading full files."""
    if b"\x00" in prefix:
        return True
    if not prefix:
        return False
    control_bytes = sum(byte < 9 or 13 < byte < 32 for byte in prefix)
    return control_bytes / len(prefix) > 0.2
