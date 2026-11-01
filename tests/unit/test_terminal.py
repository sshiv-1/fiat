import sys

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
