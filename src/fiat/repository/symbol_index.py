"""Syntax-aware symbol and import extraction without executing project code."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from fiat.repository.file_classifier import FileCategory
from fiat.repository.scanner import RepositorySnapshot


@dataclass(frozen=True)
class Symbol:
    """A named source construct with a stable file and line-range reference."""

    name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    decorators: tuple[str, ...] = ()
    exported: bool = False


@dataclass(frozen=True)
class ImportReference:
    """An import expression extracted from a source file."""

    path: str
    specifier: str
    line: int
    language: str
    names: tuple[str, ...] = ()
    level: int = 0


@dataclass
class SymbolIndex:
    """A language-dispatched symbol index with graceful parse-error retention."""

    root: Path
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)
    parse_errors: dict[str, str] = field(default_factory=dict)
    indexed_files: set[str] = field(default_factory=set)

    def build(self, snapshot: RepositorySnapshot) -> SymbolIndex:
        """Index supported source and test files from a repository snapshot."""
        for record in snapshot.files:
            if record.category not in {FileCategory.SOURCE, FileCategory.TEST}:
                continue
            if record.language not in {"Python", "JavaScript", "TypeScript"}:
                continue
            self.index_file(record.path, record.language)
        return self

    def index_file(self, relative_path: str, language: str) -> None:
        """Index one file, keeping syntax errors local to that file."""
        self.indexed_files.add(relative_path)
        path = self.root / relative_path
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.parse_errors[relative_path] = str(error)
            return
        if language == "Python":
            self._index_python(relative_path, source)
        else:
            self._index_javascript(relative_path, source, language)

    def lookup(self, name: str) -> list[Symbol]:
        """Find symbols case-insensitively by exact or partial name."""
        normalized = name.casefold()
        return [
            symbol
            for symbol in self.symbols
            if normalized in symbol.name.casefold()
        ]

    def symbols_for_file(self, path: str) -> list[Symbol]:
        """Return symbols declared in one workspace-relative file."""
        return [symbol for symbol in self.symbols if symbol.path == path]

    def _index_python(self, relative_path: str, source: str) -> None:
        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as error:
            self.parse_errors[relative_path] = f"{error.msg} at line {error.lineno}"
            return
        visitor = _PythonVisitor(relative_path)
        visitor.visit(tree)
        self.symbols.extend(visitor.symbols)
        self.imports.extend(visitor.imports)

    def _index_javascript(self, relative_path: str, source: str, language: str) -> None:
        lines = source.splitlines()
        class_ranges = _class_ranges(lines)
        for line_number, line in enumerate(lines, start=1):
            for match in _JS_IMPORT.finditer(line):
                self.imports.append(
                    ImportReference(
                        path=relative_path,
                        specifier=match.group("specifier"),
                        line=line_number,
                        language=language,
                    )
                )
            for match in _JS_REQUIRE.finditer(line):
                self.imports.append(
                    ImportReference(
                        path=relative_path,
                        specifier=match.group("specifier"),
                        line=line_number,
                        language=language,
                    )
                )
            class_match = _JS_CLASS.search(line)
            if class_match:
                self.symbols.append(
                    Symbol(
                        name=class_match.group("name"),
                        kind="class",
                        path=relative_path,
                        start_line=line_number,
                        end_line=_block_end_line(lines, line_number),
                        exported=bool(class_match.group("export")),
                    )
                )
                continue
            function_match = _JS_FUNCTION.search(line)
            arrow_match = _JS_ARROW.search(line)
            method_match = _JS_METHOD.search(line)
            declaration_match: re.Match[str] | None = function_match or arrow_match
            if declaration_match:
                name = declaration_match.group("name")
                is_component = bool(name and name[0].isupper())
                self.symbols.append(
                    Symbol(
                        name=name,
                        kind="component" if is_component else "function",
                        path=relative_path,
                        start_line=line_number,
                        end_line=_block_end_line(lines, line_number),
                        exported=bool(declaration_match.groupdict().get("export")),
                    )
                )
            elif method_match and _line_in_class(line_number, class_ranges):
                name = method_match.group("name")
                if name not in {"if", "for", "switch", "while", "catch"}:
                    self.symbols.append(
                        Symbol(
                            name=name,
                            kind="method",
                            path=relative_path,
                            start_line=line_number,
                            end_line=_block_end_line(lines, line_number),
                        )
                    )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.symbols: list[Symbol] = []
        self.imports: list[ImportReference] = []
        self._class_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append(self._symbol(node.name, "class", node, node.decorator_list))
        self._class_depth += 1
        self.generic_visit(node)
        self._class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        kind = "method" if self._class_depth else "function"
        self.symbols.append(self._symbol(node.name, kind, node, node.decorator_list))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        kind = "method" if self._class_depth else "function"
        self.symbols.append(self._symbol(node.name, kind, node, node.decorator_list))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ImportReference(
                    path=self.path,
                    specifier=alias.name,
                    line=node.lineno,
                    language="Python",
                    names=(alias.asname or alias.name.split(".")[-1],),
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append(
            ImportReference(
                path=self.path,
                specifier=node.module or "",
                line=node.lineno,
                language="Python",
                names=tuple(alias.name for alias in node.names),
                level=node.level,
            )
        )

    def _symbol(
        self,
        name: str,
        kind: str,
        node: ast.AST,
        decorators: list[ast.expr],
    ) -> Symbol:
        return Symbol(
            name=name,
            kind=kind,
            path=self.path,
            start_line=getattr(node, "lineno", 1),
            end_line=getattr(node, "end_lineno", getattr(node, "lineno", 1)),
            decorators=tuple(ast.unparse(item) for item in decorators),
        )


_JS_IMPORT = re.compile(
    r"(?:^|\s)(?:import|export)\s+(?:[^'\"]+?\s+from\s+)?[\"'](?P<specifier>[^\"']+)[\"']"
)
_JS_REQUIRE = re.compile(r"require\(\s*[\"'](?P<specifier>[^\"']+)[\"']\s*\)")
_JS_CLASS = re.compile(r"\b(?P<export>export\s+)?(?:default\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)")
_JS_FUNCTION = re.compile(
    r"\b(?P<export>export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)"
)
_JS_ARROW = re.compile(
    r"\b(?P<export>export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_JS_METHOD = re.compile(
    r"^\s*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{"
)


def _block_end_line(lines: list[str], start_line: int) -> int:
    depth = 0
    seen_block = False
    for line_number in range(start_line, len(lines) + 1):
        line = lines[line_number - 1]
        depth += line.count("{") - line.count("}")
        seen_block = seen_block or "{" in line
        if seen_block and depth <= 0:
            return line_number
    return start_line


def _class_ranges(lines: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for line_number, line in enumerate(lines, start=1):
        if _JS_CLASS.search(line):
            ranges.append((line_number, _block_end_line(lines, line_number)))
    return ranges


def _line_in_class(line_number: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < line_number <= end for start, end in ranges)
