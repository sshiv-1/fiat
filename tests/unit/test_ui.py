import io
import threading
from contextlib import redirect_stdout
from datetime import UTC, datetime

from fiat.execution.executor import PlanExecutor
from fiat.execution.store import ExecutionStore
from fiat.planning.models import Plan, PlanLifecycle, PlanTask
from fiat.planning.store import PlanStore
from fiat.tools.workspace import WorkspaceManager
from fiat.ui import (
    BRAILLE_FRAMES,
    ActivitySpinner,
    StreamPrinter,
    format_mode_badge,
    render_execution_event,
)


def test_activity_spinner_is_quiet_and_thread_free_in_non_tty(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)

    with ActivitySpinner("Thinking...") as spinner:
        spinner.update("Reading", "src/app.py")
        assert spinner.label == "Reading"
        assert spinner.file_path == "src/app.py"
        assert spinner.thread is None

    assert output.getvalue() == ""
    assert not any(
        thread.name == "fiat-activity-spinner" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_stream_printer_stops_spinner_before_first_chunk(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)

    printer = StreamPrinter()
    printer.start_thinking()
    assert printer.spinner is not None
    printer.write_chunk("Hello")
    assert printer.spinner is None
    printer.write_chunk(" world")
    printer.finish()

    assert output.getvalue() == "Hello world\n"


def test_stream_printer_consumes_generator_without_repr(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)

    def chunks():
        yield "one"
        yield " two"
        yield " three"

    assembled = StreamPrinter().write_stream(chunks())

    assert assembled == "one two three"
    assert output.getvalue() == "one two three\n"
    assert "<generator object" not in output.getvalue()


def test_activity_spinner_uses_locked_braille_frames():
    assert BRAILLE_FRAMES == (
        "⠋",
        "⠙",
        "⠹",
        "⠸",
        "⠼",
        "⠴",
        "⠦",
        "⠧",
        "⠇",
        "⠏",
    )


def test_plan_executor_reports_progress_transitions(tmp_path):
    workspace = WorkspaceManager(tmp_path)
    plan_store = PlanStore(workspace)
    plan = Plan(
        title="Progress plan",
        description="A plan for progress reporting.",
        status=PlanLifecycle.APPROVED,
        approved_at=datetime.now(UTC),
        tasks=[
            PlanTask(
                task_id="task-1",
                title="Write file",
                description="Write the target file.",
                target_files=["src/feature.py"],
                acceptance_criteria=["The file exists"],
            )
        ],
    )
    plan_store.save(plan)
    progress = []

    def task_runner(_task, _run_id):
        target = tmp_path / "src" / "feature.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("value = 1\n", encoding="utf-8")
        return True

    executor = PlanExecutor(
        plan_store=plan_store,
        execution_store=ExecutionStore(tmp_path),
        workspace_manager=workspace,
        permission_manager=None,
        task_runner=task_runner,
        on_progress=lambda task_id, state, files, detail: progress.append(
            (task_id, state, files, detail)
        ),
    )

    run = executor.execute_plan(plan.plan_id)

    assert run.lifecycle == "completed"
    assert [item[1].value for item in progress] == [
        "running",
        "verifying",
        "completed",
    ]
    assert all(item[0] == "task-1" for item in progress)
    assert all(item[2] == ["src/feature.py"] for item in progress)


def test_mode_badges_and_execution_events_are_distinct(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)

    chat = format_mode_badge("chat")
    plan = format_mode_badge("PLAN")
    event = render_execution_event(
        "task-1",
        "COMPLETED",
        ["src/fiat/ui.py"],
        "verified",
    )

    assert "[CHAT]" in chat
    assert "[PLAN]" in plan
    assert chat != plan
    assert "COMPLETED" in event
    assert "task-1" in event
    assert "src/fiat/ui.py" in event
    assert "verified" in event
    assert output.getvalue().count("COMPLETED") == 1


def test_ui_helpers_are_safe_for_cp1252(monkeypatch):
    output = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr("sys.stdout", output)

    with redirect_stdout(output):
        badge = format_mode_badge("EXEC")
        event = render_execution_event("task-2", "FAILED")

    assert "[EXEC]" in badge
    assert "FAILED" in event
