import json
import sys

from fiat.permissions import (
    OperationCategory,
    PermissionDecision,
    PermissionManager,
    PermissionRequest,
    RiskLevel,
)
from fiat.tools.filesystem import FileSystemTools
from fiat.tools.terminal import CommandRequest, TerminalExecutor
from fiat.tools.workspace import WorkspaceManager


def request(resource="src/module.py", destructive=False):
    return PermissionRequest(
        category=OperationCategory.FILE_MODIFICATION,
        operation="edit",
        resource=resource,
        reason="Apply a requested change.",
        risk=RiskLevel.MEDIUM,
        working_directory="workspace",
        destructive=destructive,
    )


def test_allow_once_does_not_grant_a_second_operation(tmp_path):
    prompts = []
    manager = PermissionManager(
        WorkspaceManager(tmp_path),
        lambda value: prompts.append(value) or PermissionDecision.ALLOW_ONCE,
    )

    assert manager.authorize(request()) is True
    assert manager.authorize(request()) is True
    assert len(prompts) == 2


def test_session_and_workspace_grants_are_exact_and_persisted(tmp_path):
    workspace = WorkspaceManager(tmp_path)
    prompts = []
    manager = PermissionManager(
        workspace,
        lambda value: prompts.append(value) or PermissionDecision.ALLOW_SESSION,
    )

    assert manager.authorize(request()) is True
    assert manager.authorize(request()) is True
    assert manager.authorize(request("src/other.py")) is True
    assert len(prompts) == 2

    persisted = PermissionManager(
        workspace, lambda _value: PermissionDecision.ALLOW_WORKSPACE
    )
    assert persisted.authorize(request("src/persistent.py")) is True
    reloaded = PermissionManager(workspace, lambda _value: PermissionDecision.DENY)
    assert reloaded.authorize(request("src/persistent.py")) is True
    assert reloaded.authorize(request("src/unrelated.py")) is False
    assert (tmp_path / ".fiat" / "permissions.json").is_file()
    assert (tmp_path / ".fiat" / "permission-audit.json").is_file()

    policies = tmp_path / ".fiat" / "permissions.json"
    malformed = json.loads(policies.read_text(encoding="utf-8"))
    malformed["grants"][0]["resource"] = "src/forged.py"
    policies.write_text(json.dumps(malformed), encoding="utf-8")
    corrupted = PermissionManager(workspace, lambda _value: PermissionDecision.DENY)
    assert corrupted.authorize(request("src/persistent.py")) is False


def test_destructive_operations_never_inherit_persistent_permissions(tmp_path):
    manager = PermissionManager(
        WorkspaceManager(tmp_path), lambda _value: PermissionDecision.ALLOW_WORKSPACE
    )
    destructive = manager.classify_command(
        CommandRequest(("git", "reset", "--hard")), "Reset repository"
    )

    assert destructive.destructive is True
    assert destructive.category == OperationCategory.DESTRUCTIVE_OPERATION
    assert manager.authorize(destructive) is False

    push = manager.classify_command(
        CommandRequest(("git", "push", "origin", "main")), "Publish changes"
    )
    assert push.can_persist_workspace_grant is False
    assert manager.authorize(push) is False

    clone = manager.classify_command(
        CommandRequest(("git", "clone", "https://example.invalid/repository.git")),
        "Clone repository",
    )
    assert clone.category == OperationCategory.NETWORK_OPERATION
    assert clone.can_persist_workspace_grant is False


def test_authorization_fails_closed_and_blocks_file_and_command_boundaries(tmp_path):
    workspace = WorkspaceManager(tmp_path)
    manager = PermissionManager(workspace, lambda _value: PermissionDecision.DENY)
    tools = FileSystemTools(workspace, manager.authorize_file_modification)
    terminal = TerminalExecutor(workspace, authorization_callback=lambda value: manager.authorize_command(value, "Run test"))

    assert "Permission denied" in tools.edit_file("blocked.py", "value = 1\n")
    assert not (tmp_path / "blocked.py").exists()
    result = terminal.execute([sys.executable, "-c", "print('should not run')"])
    assert result.status == "cancelled"

    failing = PermissionManager(workspace, lambda _value: (_ for _ in ()).throw(RuntimeError("broken prompt")))
    assert failing.authorize(request("src/fail.py")) is False
