import json

from fiat.repository.context_builder import ContextBuilder
from fiat.repository.file_classifier import FileCategory, classify_file
from fiat.repository.import_graph import ImportGraph
from fiat.repository.scanner import RepositoryScanner
from fiat.repository.search import RepositorySearch
from fiat.repository.symbol_index import SymbolIndex
from fiat.tools.workspace import WorkspaceManager


def test_scanner_respects_ignore_rules_detects_languages_and_skips_non_source(sample_repository):
    (sample_repository / ".env").write_text("API_KEY=not-indexed")
    snapshot = RepositoryScanner(WorkspaceManager(sample_repository)).scan()
    paths = {file.path for file in snapshot.files}

    assert snapshot.root == sample_repository
    assert set(snapshot.languages) == {"Python", "TypeScript"}
    assert "pkg/a.py" in paths
    assert "frontend/src/Widget.tsx" in paths
    assert "ignored/ignored.py" not in paths
    assert "asset.bin" not in paths
    assert "generated/client.generated.py" not in paths
    assert ".env" not in paths
    assert "React" in snapshot.frameworks
    assert "tests" in snapshot.test_directories


def test_classification_covers_expected_categories():
    assert classify_file(__import__("pathlib").Path("src/main.py")) == FileCategory.SOURCE
    assert classify_file(__import__("pathlib").Path("tests/test_main.py")) == FileCategory.TEST
    assert classify_file(__import__("pathlib").Path("docs/guide.md")) == FileCategory.DOCUMENTATION
    assert classify_file(__import__("pathlib").Path("dist/app.min.js")) == FileCategory.GENERATED


def test_symbol_index_and_dependency_graph_handle_cycles_and_syntax_errors(sample_repository):
    snapshot = RepositoryScanner(WorkspaceManager(sample_repository)).scan()
    index = SymbolIndex(snapshot.root).build(snapshot)
    graph = ImportGraph.build(index)

    assert any(symbol.name == "collision_detector" for symbol in index.lookup("collision"))
    assert any(symbol.kind == "method" for symbol in index.symbols_for_file("pkg/b.py"))
    assert any(symbol.kind == "component" for symbol in index.lookup("CollisionPanel"))
    assert "broken.py" in index.parse_errors
    assert graph.dependencies("pkg/a.py")[0].target == "pkg/b.py"
    assert graph.dependencies("pkg/b.py")[0].target == "pkg/a.py"


def test_search_and_context_builder_return_bounded_relevant_evidence(sample_repository):
    workspace = WorkspaceManager(sample_repository)
    snapshot = RepositoryScanner(workspace).scan()
    index = SymbolIndex(snapshot.root).build(snapshot)
    graph = ImportGraph.build(index)
    search = RepositorySearch(snapshot, index, graph)
    builder = ContextBuilder(workspace)
    context = builder.build(
        "Fix vehicle collision detection", token_budget=90, max_files=2, max_snippets=2
    )
    destination = builder.save_project_context(context)

    assert any(match.path == "pkg/a.py" for match in search.regex_search("collision"))
    assert any(item.path == "pkg/a.py" for item in context.snippets)
    assert context.estimated_tokens <= 90
    assert len(context.snippets) <= 2
    assert "content" not in json.loads(destination.read_text())["files"][0]


def test_instruction_precedence_is_low_to_high_with_fiat_last(sample_repository):
    (sample_repository / "CLAUDE.md").write_text("base instruction")
    (sample_repository / "AGENTS.md").write_text("agent instruction")
    (sample_repository / "FIAT.md").write_text("fiat instruction")

    snapshot = RepositoryScanner(WorkspaceManager(sample_repository)).scan()

    assert [item.path for item in snapshot.instructions] == [
        "CLAUDE.md",
        "AGENTS.md",
        "FIAT.md",
    ]


def test_scanner_supports_cancellation_and_large_repository_bounds(sample_repository):
    bulk = sample_repository / "bulk"
    bulk.mkdir()
    for index in range(40):
        (bulk / f"module_{index}.py").write_text(f"value_{index} = {index}\n")
    scanner = RepositoryScanner(WorkspaceManager(sample_repository))

    cancelled = scanner.scan(cancel_check=lambda: True)
    bounded = scanner.scan(max_files=10)

    assert cancelled.cancelled is True
    assert bounded.max_files_reached is True
