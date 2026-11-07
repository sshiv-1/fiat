from fiat.cli import FiatCore, _handle_mode_command
from fiat.modes import InteractionMode, ModeController, build_mode_key_bindings
from fiat.permissions import PermissionDecision


def test_mode_controller_toggle_and_terminal_sequences():
    controller = ModeController(InteractionMode.PLAN)

    assert controller.prompt == "Plan > "
    assert controller.toggle() == InteractionMode.WORK
    assert controller.prompt == "Work > "
    assert controller.is_shift_tab_sequence("\x1b[Z")
    assert controller.is_shift_tab_sequence("\x1b[1;2Z")
    assert not controller.is_shift_tab_sequence("\t")

    invalidated = []

    class Event:
        class App:
            @staticmethod
            def invalidate():
                invalidated.append(True)

        app = App()

    bindings = build_mode_key_bindings(controller.toggle)
    bindings.bindings[0].handler(Event())
    assert controller.mode == InteractionMode.PLAN
    assert invalidated == [True]


def test_mode_commands_preserve_core_conversation_and_plan_mode_blocks_writes(tmp_path):
    core = FiatCore(tmp_path, lambda _request: PermissionDecision.ALLOW_ONCE)
    core.conversation_history.append(("user", "Keep this context"))

    assert "Current mode: WORK" in _handle_mode_command(core, "")
    assert _handle_mode_command(core, "plan") == "Switched to PLAN MODE."
    assert core.conversation_history == [("user", "Keep this context")]
    assert "read-only" in core.edit_file("blocked.py", "value = 1\n")
    assert "read-only" in core.run_command("python --version")
    assert not (tmp_path / "blocked.py").exists()
    assert _handle_mode_command(core, "work") == "Switched to WORK MODE."
