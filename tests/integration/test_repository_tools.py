import sys

from fiat import cli
from fiat.repository.repo_map import run_repository_command
from fiat.tools.workspace import WorkspaceManager


def test_repository_commands_render_actual_indexed_information(sample_repository):
    workspace = WorkspaceManager(sample_repository)

    mapped = run_repository_command("/map", [], workspace)
    searched = run_repository_command("/search", ["collision"], workspace)
    symbols = run_repository_command("/symbol", ["collision_detector"], workspace)
    indexed = run_repository_command("/index", [], workspace)

    assert "Python" in mapped
    assert "pkg/a.py" in searched
    assert "collision_detector pkg/a.py" in symbols
    assert "Index metadata: .agent" in indexed
    assert (sample_repository / ".agent" / "repository-index.json").is_file()


def test_cli_repository_command_bypasses_provider_setup(sample_repository, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["fiat", "--workspace", str(sample_repository), "/symbol", "collision_detector"],
    )

    cli.main()

    assert "collision_detector pkg/a.py" in capsys.readouterr().out
