"""Terminal UI helpers for Fiat's interactive command-line experience."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

import questionary

RESET = "\033[0m"
PALETTE = {
    "cyan": "\033[36m",
    "magenta": "\033[35m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "red": "\033[31m",
    "dim": "\033[2m",
    "orange": "\033[38;5;208m",
}
MODE_STYLES = {
    "CHAT": "cyan",
    "ASK": "cyan",
    "PLAN": "magenta",
    "WORK": "yellow",
    "EXEC": "green",
    "EXECUTE": "green",
}
EXECUTION_STYLES = {
    "QUEUED": "dim",
    "RUNNING": "yellow",
    "VERIFYING": "cyan",
    "AWAITING_PERMISSION": "magenta",
    "COMPLETED": "green",
    "FAILED": "red",
    "CANCELLED": "red",
    "RETRYING": "orange",
}
BRAILLE_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
# Backwards-compatible alias for callers that used the earlier name.
UTF8_FRAMES = BRAILLE_FRAMES
ASCII_FRAMES = (". ", ".. ", "...", " ..", " .", " ")


def _supports_utf8(stream: TextIO) -> bool:
    encoding = getattr(stream, "encoding", None) or ""
    return "utf" in encoding.casefold()


def _color(text: str, style: str, stream: TextIO | None = None) -> str:
    if stream is not None and not stream.isatty():
        return text
    return f"{PALETTE.get(style, '')}{text}{RESET}"


def _terminal_symbol(symbol: str, fallback: str, stream: TextIO) -> str:
    return symbol if _supports_utf8(stream) else fallback


def format_mode_badge(mode_name: str) -> str:
    """Return a color-coded, normalized mode badge."""
    mode = str(mode_name).strip().upper()
    style = MODE_STYLES.get(mode, "dim")
    return _color(f"[{mode}]", style)


def render_status_bar(
    mode: str,
    model: str,
    workspace: str,
    active_file: str | None = None,
) -> str:
    """Render a compact status line for the current agent activity."""
    workspace_name = Path(workspace).name or workspace or "."
    parts = [
        format_mode_badge(mode),
        f"model={model}",
        f"workspace={workspace_name}",
    ]
    if active_file:
        parts.append(f"file={active_file}")
    return "  ".join(parts)


class ActivitySpinner:
    """Threaded terminal activity indicator with a quiet non-TTY mode."""

    def __init__(
        self,
        label: str,
        file_path: str | None = None,
        style: str = "cyan",
    ) -> None:
        self.label = label
        self.file_path = file_path
        self.style = style
        self._stream = sys.stdout
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._started_at = 0.0
        self._active = False
        self._frame_index = 0

    @property
    def thread(self) -> threading.Thread | None:
        """Expose the worker for lifecycle assertions and diagnostics."""
        return self._thread

    def __enter__(self) -> ActivitySpinner:
        self._stream = sys.stdout
        self._started_at = time.monotonic()
        self._active = True
        if self._stream.isatty():
            self._thread = threading.Thread(
                target=self._run,
                name="fiat-activity-spinner",
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        self.stop(success=exc_type is None, emit_final=self._stream.isatty())
        return False

    def update(
        self,
        label: str | None = None,
        file_path: str | None = None,
    ) -> None:
        """Update the displayed operation without restarting the spinner."""
        with self._lock:
            if label is not None:
                self.label = label
            if file_path is not None:
                self.file_path = file_path

    def stop(self, success: bool = True, emit_final: bool = True) -> None:
        """Stop the worker and optionally print a final terminal status."""
        if not self._active:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        elapsed = time.monotonic() - self._started_at
        with self._lock:
            label = self.label
            file_path = self.file_path
        if self._stream.isatty():
            self._clear_line()
            if emit_final:
                symbol = _terminal_symbol("✓" if success else "✗", "[OK]" if success else "[FAIL]", self._stream)
                status = self._format_message(symbol, label, file_path, elapsed)
                color = "green" if success else "red"
                self._stream.write(_color(status, color, self._stream) + "\n")
                self._stream.flush()
        self._active = False

    def _run(self) -> None:
        frames = BRAILLE_FRAMES if _supports_utf8(self._stream) else ASCII_FRAMES
        while not self._stop_event.wait(0.08):
            elapsed = time.monotonic() - self._started_at
            with self._lock:
                frame = frames[self._frame_index % len(frames)]
                self._frame_index += 1
                message = self._format_message(frame, self.label, self.file_path, elapsed)
            self._stream.write("\r" + _color(message, self.style, self._stream))
            self._stream.flush()

    @staticmethod
    def _format_message(
        prefix: str,
        label: str,
        file_path: str | None,
        elapsed: float,
    ) -> str:
        target = f" {file_path}" if file_path else ""
        return f"{prefix} {label}{target} ({elapsed:.1f}s)"

    def _clear_line(self) -> None:
        self._stream.write("\r\033[2K")

    def pause(self) -> None:
        """Stop the animation without emitting a completion status."""
        self.stop(emit_final=False)


class StreamPrinter:
    """Stream provider output while replacing any thinking spinner cleanly."""

    def __init__(self) -> None:
        self._spinner: ActivitySpinner | None = None
        self._wrote_chunk = False
        self._last_chunk = ""

    @property
    def spinner(self) -> ActivitySpinner | None:
        return self._spinner

    def start_thinking(self, label: str = "Thinking...") -> None:
        if self._spinner is not None:
            self._spinner.stop(emit_final=False)
        self._spinner = ActivitySpinner(label)
        self._spinner.__enter__()

    def write_chunk(self, text: str) -> None:
        if not text:
            return
        if self._spinner is not None:
            self._spinner.stop(emit_final=False)
            self._spinner = None
        sys.stdout.write(text)
        sys.stdout.flush()
        self._wrote_chunk = True
        self._last_chunk = text

    def finish(self) -> None:
        if self._spinner is not None:
            self._spinner.stop(emit_final=False)
            self._spinner = None
        if self._wrote_chunk and not self._last_chunk.endswith("\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._wrote_chunk = False
        self._last_chunk = ""

    def write_stream(self, chunks: Iterable[str]) -> str:
        """Write every streamed chunk and return the assembled response."""
        collected: list[str] = []
        if self._spinner is None:
            self.start_thinking()
        try:
            for chunk in chunks:
                if chunk:
                    self.write_chunk(chunk)
                    collected.append(chunk)
        finally:
            self.finish()
        return "".join(collected)

    def consume(self, chunks: Iterable[str]) -> str:
        """Compatibility alias for consuming a streamed response."""
        return self.write_stream(chunks)


def render_execution_event(
    task_id: str,
    state: str,
    target_files: list[str] | None = None,
    detail: str | None = None,
) -> str:
    """Print and return a concise, color-coded execution status line."""
    normalized_state = str(state).strip().upper()
    style = EXECUTION_STYLES.get(normalized_state, "dim")
    files = ", ".join(target_files or [])
    suffix = f" [{files}]" if files else ""
    detail_suffix = f" — {detail}" if detail else ""
    line = f"{normalized_state:<20} {task_id}{suffix}{detail_suffix}"
    rendered = _color(line, style)
    print(rendered, flush=True)
    return rendered


def interactive_select(title: str, options: list[str]) -> str | None:
    if not options:
        return None

    custom_style = questionary.Style(
        [
            ("qmark", "fg:#673ab7 bold"),
            ("question", "bold"),
            ("answer", "fg:#f44336 bold"),
            ("pointer", "fg:#673ab7 bold"),
            ("highlighted", "fg:#673ab7 bold"),
            ("selected", "fg:#cc5454"),
            ("separator", "fg:#cc5454"),
            ("instruction", ""),
            ("text", ""),
            ("disabled", "fg:#858585 italic"),
        ]
    )

    try:
        result = questionary.select(
            title,
            choices=options,
            instruction="(↑/↓ Navigate, Enter Select, Esc Cancel)",
            style=custom_style,
        ).ask()
        return result
    except KeyboardInterrupt:
        return None
