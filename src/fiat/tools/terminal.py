"""Policy-controlled command execution for Fiat's terminal tool."""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from fiat.tools.workspace import WorkspaceManager

_SHELL_CONTROL_CHARACTERS = frozenset("|&;><`$")
_SECRET_ENV_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY")
_READ_ONLY_GIT_SUBCOMMANDS = {
    "branch",
    "diff",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "status",
}


@dataclass(frozen=True)
class CommandRequest:
    """A parsed command invocation with no shell interpretation."""

    args: tuple[str, ...]
    timeout_seconds: int = 60


@dataclass(frozen=True)
class TerminalResult:
    """Structured result for a command execution attempt."""

    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    output_truncated: bool = False

    def format(self, output_limit: int = 8_000) -> str:
        """Render a backwards-compatible string response for provider tools."""
        output = (self.stdout or "") + (self.stderr or "")
        if len(output) > output_limit:
            output = output[:output_limit] + "\n...(output truncated)"
        elif self.output_truncated:
            output += "\n...(output truncated)"
        if self.status == "cancelled":
            return "Command cancelled: explicit approval was not granted."
        if self.status == "blocked":
            return f"Command blocked: {self.stderr}"
        if self.timed_out:
            return f"Command timed out.\n{output}".rstrip()
        if self.status == "error":
            return f"Command execution error: {self.stderr}".rstrip()
        return f"Exit code {self.exit_code}\n{output}".rstrip()


class CommandPolicy:
    """Classifies commands and requires consent for non-read-only execution."""

    def parse(self, command: str | Sequence[str], timeout_seconds: int = 60) -> CommandRequest:
        """Parse a command string or arguments without invoking a shell."""
        if isinstance(command, str):
            if not command.strip():
                raise ValueError("Command is empty.")
            if any(character in command for character in _SHELL_CONTROL_CHARACTERS):
                raise ValueError("Shell operators are not supported; pass one command only.")
            try:
                parsed = shlex.split(command, posix=False)
            except ValueError as error:
                raise ValueError(f"Invalid command syntax: {error}") from error
            args = tuple(self._strip_quotes(part) for part in parsed)
        else:
            args = tuple(str(part) for part in command)
        if not args or not args[0]:
            raise ValueError("Command is empty.")
        if timeout_seconds < 1 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 1 and 300.")
        return CommandRequest(args=args, timeout_seconds=timeout_seconds)

    @staticmethod
    def _strip_quotes(value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value

    def requires_approval(self, request: CommandRequest) -> bool:
        """Return true unless the command is explicitly classified read-only."""
        executable = Path(request.args[0]).name.lower()
        if executable in {"rg", "rg.exe"}:
            return False
        if executable in {"git", "git.exe"} and len(request.args) > 1:
            return request.args[1].lower() not in _READ_ONLY_GIT_SUBCOMMANDS
        if executable in {"python", "python.exe", "py", "py.exe"}:
            return not any(argument in {"--version", "-V"} for argument in request.args[1:])
        return True


@dataclass
class _BoundedOutput:
    """Collect process output up to one shared cap while always draining pipes."""

    limit: int
    stdout_parts: list[str]
    stderr_parts: list[str]
    captured: int = 0
    truncated: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, stream_name: str, value: str) -> None:
        """Append available output while discarding excess bytes safely."""
        with self.lock:
            remaining = self.limit - self.captured
            if remaining <= 0:
                self.truncated = True
                return
            retained = value[:remaining]
            if stream_name == "stdout":
                self.stdout_parts.append(retained)
            else:
                self.stderr_parts.append(retained)
            self.captured += len(retained)
            if len(retained) < len(value):
                self.truncated = True

    def values(self) -> tuple[str, str, bool]:
        """Return the bounded streams and whether any content was discarded."""
        return "".join(self.stdout_parts), "".join(self.stderr_parts), self.truncated


class TerminalExecutor:
    """Executes one approved process in the workspace with protected environment data."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        policy: CommandPolicy | None = None,
        output_limit: int = 8_000,
    ) -> None:
        self.workspace = workspace
        self.policy = policy or CommandPolicy()
        self.output_limit = output_limit

    def execute(
        self,
        command: str | Sequence[str],
        timeout_seconds: int = 60,
        approval_callback: Callable[[CommandRequest], bool] | None = None,
    ) -> TerminalResult:
        """Run an approved command with ``shell=False`` and bounded output."""
        try:
            request = self.policy.parse(command, timeout_seconds)
        except ValueError as error:
            return TerminalResult("blocked", None, "", str(error))

        if self.policy.requires_approval(request):
            approved = approval_callback(request) if approval_callback else False
            if not approved:
                return TerminalResult("cancelled", None, "", "Approval was not granted.")

        logging.info("run_command: %s", self._redact_args(request.args))
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                list(request.args),
                cwd=self.workspace.root,
                env=self._protected_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=self._creation_flags(),
            )
            collector = _BoundedOutput(self.output_limit, [], [])
            readers: list[threading.Thread] = []
            try:
                readers = self._start_readers(process, collector)
                timed_out = False
                try:
                    process.wait(timeout=request.timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._terminate_process(process)
            except KeyboardInterrupt:
                self._terminate_process(process)
                raise
            finally:
                for reader in readers:
                    reader.join(timeout=5)
            stdout, stderr, output_truncated = collector.values()
            if timed_out:
                return TerminalResult(
                    "timeout",
                    None,
                    stdout,
                    stderr,
                    timed_out=True,
                    output_truncated=output_truncated,
                )
            return TerminalResult(
                "completed",
                process.returncode,
                stdout,
                stderr,
                output_truncated=output_truncated,
            )
        except OSError as error:
            return TerminalResult("error", None, "", str(error))

    @staticmethod
    def _creation_flags() -> int:
        """Return platform-specific flags for the child process."""
        if os.name != "nt":
            return 0
        return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    @staticmethod
    def _start_readers(
        process: subprocess.Popen[str], collector: _BoundedOutput
    ) -> list[threading.Thread]:
        readers = [
            threading.Thread(
                target=TerminalExecutor._drain_stream,
                args=(process.stdout, "stdout", collector),
                daemon=True,
            ),
            threading.Thread(
                target=TerminalExecutor._drain_stream,
                args=(process.stderr, "stderr", collector),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()
        return readers

    @staticmethod
    def _drain_stream(
        stream: TextIO | None, stream_name: str, collector: _BoundedOutput
    ) -> None:
        if stream is None:
            return
        while chunk := stream.read(4_096):
            collector.add(stream_name, chunk)

    @staticmethod
    def _protected_environment() -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in _SECRET_ENV_MARKERS)
        }

    @staticmethod
    def _redact_args(args: Sequence[str]) -> list[str]:
        redacted: list[str] = []
        for argument in args:
            if any(marker.lower() in argument.lower() for marker in _SECRET_ENV_MARKERS):
                redacted.append("[REDACTED]")
            else:
                redacted.append(argument)
        return redacted

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        """Terminate the direct process and its Windows child-process tree."""
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
            )
            return
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
