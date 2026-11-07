import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

import fiat.tools.terminal as terminal_module
from fiat.tools.terminal import TerminalExecutor
from fiat.tools.workspace import WorkspaceManager


def test_terminal_runs_structured_approved_command(tmp_path):
    executor = TerminalExecutor(WorkspaceManager(tmp_path))

    result = executor.execute(
        [sys.executable, "-c", "print('ok')"],
        approval_callback=lambda _: True,
    )

    assert result.status == "completed"
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"


def test_terminal_blocks_shell_operators_and_unapproved_writes(tmp_path):
    executor = TerminalExecutor(WorkspaceManager(tmp_path))

    shell_result = executor.execute("echo first | echo second")
    unapproved_result = executor.execute(["git", "commit", "-m", "message"])

    assert shell_result.status == "blocked"
    assert unapproved_result.status == "cancelled"


def test_terminal_reports_exit_codes_and_timeouts(tmp_path):
    executor = TerminalExecutor(WorkspaceManager(tmp_path))

    failed = executor.execute(
        [sys.executable, "-c", "raise SystemExit(7)"],
        approval_callback=lambda _: True,
    )
    timed_out = executor.execute(
        [sys.executable, "-c", "import time; time.sleep(3)"],
        timeout_seconds=1,
        approval_callback=lambda _: True,
    )

    assert failed.exit_code == 7
    assert timed_out.timed_out is True


def test_terminal_strips_secret_environment_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMPLE_SECRET_TOKEN", "do-not-leak")
    executor = TerminalExecutor(WorkspaceManager(tmp_path))

    result = executor.execute(
        [sys.executable, "-c", "import os; print(os.getenv('EXAMPLE_SECRET_TOKEN'))"],
        approval_callback=lambda _: True,
    )

    assert result.stdout.strip() == "None"


def test_terminal_bounds_captured_output_while_draining_the_process(tmp_path):
    executor = TerminalExecutor(WorkspaceManager(tmp_path), output_limit=128)

    result = executor.execute(
        [sys.executable, "-c", "print('x' * 10000)"],
        approval_callback=lambda _: True,
    )

    assert result.exit_code == 0
    assert len(result.stdout) + len(result.stderr) <= 128
    assert result.output_truncated is True


def test_terminal_uses_windows_process_group_flag(monkeypatch):
    monkeypatch.setattr(terminal_module.os, "name", "nt")
    monkeypatch.setattr(terminal_module.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)

    assert TerminalExecutor._creation_flags() == 512


def test_terminal_uses_no_process_group_flag_on_posix(monkeypatch):
    monkeypatch.setattr(terminal_module.os, "name", "posix")

    assert TerminalExecutor._creation_flags() == 0


def test_terminal_forwards_popen_arguments_and_workspace(tmp_path):
    process = Mock()
    process.stdout = None
    process.stderr = None
    process.returncode = 0
    executor = TerminalExecutor(WorkspaceManager(tmp_path))

    with patch.object(terminal_module.subprocess, "Popen", return_value=process) as popen:
        result = executor.execute(
            ["python", "-c", "print('ok')"],
            approval_callback=lambda _: True,
        )

    assert result.status == "completed"
    process.wait.assert_called_once_with(timeout=60)
    popen.assert_called_once()
    kwargs = popen.call_args.kwargs
    assert popen.call_args.args == (["python", "-c", "print('ok')"],)
    assert kwargs["cwd"] == tmp_path
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is terminal_module.subprocess.DEVNULL
    assert kwargs["stdout"] is terminal_module.subprocess.PIPE
    assert kwargs["stderr"] is terminal_module.subprocess.PIPE
    assert kwargs["creationflags"] == TerminalExecutor._creation_flags()


def test_terminal_terminates_process_when_interrupted(tmp_path):
    process = Mock()
    process.stdout = None
    process.stderr = None
    process.wait.side_effect = KeyboardInterrupt
    executor = TerminalExecutor(WorkspaceManager(tmp_path))

    with (
        patch.object(terminal_module.subprocess, "Popen", return_value=process),
        patch.object(executor, "_start_readers", return_value=[]),
        patch.object(executor, "_terminate_process") as terminate,
        pytest.raises(KeyboardInterrupt),
    ):
        executor.execute(
            ["python", "-c", "print('ok')"],
            approval_callback=lambda _: True,
        )

    terminate.assert_called_once_with(process)


def test_terminal_timeout_terminates_process_and_preserves_output(tmp_path):
    process = Mock()
    process.stdout = None
    process.stderr = None
    process.returncode = -15
    process.wait.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=1)
    executor = TerminalExecutor(WorkspaceManager(tmp_path))

    with (
        patch.object(terminal_module.subprocess, "Popen", return_value=process),
        patch.object(executor, "_start_readers", return_value=[]),
        patch.object(executor, "_terminate_process") as terminate,
    ):
        result = executor.execute(
            ["python", "-c", "print('ok')"],
            timeout_seconds=1,
            approval_callback=lambda _: True,
        )

    assert result.timed_out is True
    terminate.assert_called_once_with(process)


def test_terminal_reaps_process_after_posix_kill(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="python", timeout=2),
        None,
    ]
    monkeypatch.setattr(terminal_module.os, "name", "posix")

    TerminalExecutor._terminate_process(process)

    process.send_signal.assert_called_once_with(terminal_module.signal.SIGTERM)
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2
