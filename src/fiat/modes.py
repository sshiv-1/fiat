"""Interaction mode state and cross-terminal Shift+Tab recognition."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from prompt_toolkit.key_binding import KeyBindings


class InteractionMode(StrEnum):
    PLAN = "PLAN"
    WORK = "WORK"


_SHIFT_TAB_SEQUENCES = frozenset({"\x1b[Z", "\x1b[1;2Z", "\x1b[2Z"})


class ModeController:
    """Owns the current mode without altering conversation or workspace state."""

    def __init__(self, mode: InteractionMode = InteractionMode.WORK) -> None:
        self._mode = mode

    @property
    def mode(self) -> InteractionMode:
        return self._mode

    @property
    def prompt(self) -> str:
        return "Plan > " if self._mode == InteractionMode.PLAN else "Work > "

    def set_mode(self, mode: InteractionMode | str) -> InteractionMode:
        self._mode = InteractionMode(str(mode).upper())
        return self._mode

    def toggle(self) -> InteractionMode:
        self._mode = (
            InteractionMode.WORK
            if self._mode == InteractionMode.PLAN
            else InteractionMode.PLAN
        )
        return self._mode

    @staticmethod
    def is_shift_tab_sequence(sequence: str) -> bool:
        """Recognize common BackTab sequences when a terminal exposes raw input."""
        return sequence in _SHIFT_TAB_SEQUENCES


def build_mode_key_bindings(toggle: Callable[[], InteractionMode]) -> KeyBindings:
    """Bind prompt-toolkit's portable BackTab key without inserting text."""
    bindings = KeyBindings()

    @bindings.add("s-tab")
    def toggle_mode(event: object) -> None:
        toggle()
        app = getattr(event, "app", None)
        invalidate = getattr(app, "invalidate", None)
        if callable(invalidate):
            invalidate()

    return bindings
