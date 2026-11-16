from datetime import UTC, datetime
from pathlib import Path
from fiat.planning.models import Plan, PlanTask, PlanLifecycle
from fiat.planning.store import PlanStore
from fiat.tools.workspace import WorkspaceManager
from fiat.execution import ExecutionStore, TaskVerifier, RunLifecycle, TaskExecutionState, CommandVerificationResult


def _approved_plan(task_id: str = "task_t1") -> Plan:
    """Helper: build a minimal APPROVED plan that passes all validators."""
    task = PlanTask(
        task_id=task_id,
        title="Implement feature",
        description="Write the initial implementation of the feature module.",
        target_files=["src/feature.py"],
        acceptance_criteria=["All unit tests pass"],
    )
    return Plan(
        title="Test Plan",
        description="A plan used in automated unit tests to verify execution behaviour.",
        status=PlanLifecycle.APPROVED,
        approved_at=datetime.now(UTC),
        tasks=[task],
    )


def _draft_plan(task_id: str = "task_t1") -> Plan:
    task = PlanTask(
        task_id=task_id,
        title="Implement feature",
        description="Write the initial implementation of the feature module.",
        target_files=["src/feature.py"],
        acceptance_criteria=["All unit tests pass"],
    )
    return Plan(
        title="Test Plan",
        description="A plan used in automated unit tests to verify execution behaviour.",
        tasks=[task],
    )


def test_execution_store_rejects_unapproved_plan_and_keeps_plan_file_immutable(tmp_path):
    ws = WorkspaceManager(tmp_path)
    store = PlanStore(ws)

    draft = _draft_plan()
    plan_path = store.save(draft)

    exec_store = ExecutionStore(tmp_path)
    plan_bytes = plan_path.read_bytes()

    try:
        exec_store.create_run(draft, plan_bytes)
        assert False, "Expected ValueError for unapproved plan"
    except ValueError:
        pass

    approved = _approved_plan(draft.tasks[0].task_id)
    plan_path2 = store.save(approved)
    plan_bytes_before = plan_path2.read_bytes()

    run = exec_store.create_run(approved, plan_bytes_before)
    assert run.lifecycle == RunLifecycle.CREATED

    plan_bytes_after = plan_path2.read_bytes()
    assert plan_bytes_before == plan_bytes_after


def test_snapshot_and_restore_target_files_rolls_back_partial_edits_and_new_files(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("print('v1')\n", encoding="utf-8")
    b = tmp_path / "b.py"  # non-existent

    exec_store = ExecutionStore(tmp_path)
    plan = _approved_plan()
    run = exec_store.create_run(plan, b'{}', execution_order=[plan.tasks[0].task_id])

    exec_store.snapshot_target_files(run.run_id, plan.tasks[0].task_id, ["a.py", "b.py"])

    # mutate a.py and create b.py
    a.write_text("print('broken')\n", encoding="utf-8")
    b.write_text("print('new')\n", encoding="utf-8")

    restored = exec_store.restore_target_files(run.run_id, plan.tasks[0].task_id)
    assert "a.py" in restored
    assert "b.py" in restored
    assert a.read_text(encoding="utf-8") == "print('v1')\n"
    assert not b.exists()


def test_task_verifier_rejects_broken_python_syntax_and_nonzero_command_exit(tmp_path):
    py_file = tmp_path / "app.py"
    py_file.write_text("def broken(:\n", encoding="utf-8")

    class DummyTask:
        target_files = ["app.py"]

    ev = TaskVerifier.verify_task(DummyTask(), tmp_path)
    assert ev.verified is False
    assert ev.file_checks[0].syntax_valid is False

    # fix syntax
    py_file.write_text("def ok():\n    return 1\n", encoding="utf-8")

    def runner(cmd):
        return CommandVerificationResult(command=cmd, exit_code=1, passed=False)

    ev2 = TaskVerifier.verify_task(DummyTask(), tmp_path, command_runner=runner, verification_commands=["pytest"])
    assert ev2.verified is False

    def runner_pass(cmd):
        return CommandVerificationResult(command=cmd, exit_code=0, passed=True)

    ev3 = TaskVerifier.verify_task(DummyTask(), tmp_path, command_runner=runner_pass, verification_commands=["pytest"])
    assert ev3.verified is True
