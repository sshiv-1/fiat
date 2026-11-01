from fiat.tools.filesystem import FileSystemTools
from fiat.tools.workspace import WorkspaceManager


def test_valid_read_edit_and_multi_edit_stay_in_workspace(tmp_path):
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("value = 1\nvalue = 2\n")
    tools = FileSystemTools(WorkspaceManager(tmp_path))

    assert "value = 1" in tools.read_file("src/module.py")
    assert "Successfully edited" in tools.edit_file(
        "src/module.py", "value = 3", "value = 1"
    )
    assert "Successfully applied" in tools.multi_edit(
        "src/module.py",
        [{"old_text": "value = 2", "new_text": "value = 4"}],
    )
    assert source.read_text() == "value = 3\nvalue = 4\n"


def test_existing_file_is_not_silently_overwritten(tmp_path):
    target = tmp_path / "important.py"
    target.write_text("original")
    tools = FileSystemTools(WorkspaceManager(tmp_path))

    result = tools.edit_file("important.py", "replacement")

    assert "Refusing to overwrite" in result
    assert target.read_text() == "original"


def test_path_traversal_and_sensitive_files_are_rejected(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    (tmp_path / ".env").write_text("SECRET=value")
    tools = FileSystemTools(WorkspaceManager(tmp_path))

    assert "outside workspace" in tools.read_file("../outside.txt")
    assert "protected file" in tools.read_file(".env")
    assert "protected file" in tools.edit_file(".env", "x")
    (tmp_path / "credential.json").write_text('{"token": "secret"}')
    assert "protected file" in tools.read_file("credential.json")


def test_glob_and_search_return_workspace_relative_results(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "one.py").write_text("needle = 1\n")
    tools = FileSystemTools(WorkspaceManager(tmp_path))

    assert "nested/one.py" in tools.glob_files("**/*.py")
    assert "nested/one.py:1:needle = 1" in tools.grep_search("needle")


def test_symlink_escape_is_rejected_when_supported(tmp_path):
    outside = tmp_path.parent / "outside-dir"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    tools = FileSystemTools(WorkspaceManager(tmp_path))

    assert "outside workspace" in tools.read_file("link/secret.txt")
