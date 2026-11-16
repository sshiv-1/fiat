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


# ---------------------------------------------------------------------------
# Phase 4 tests
# ---------------------------------------------------------------------------

def _two_task_approved_plan() -> Plan:
    """Plan with t1 -> t2 dependency chain, both APPROVED."""
    t1 = PlanTask(
        task_id="task_t1",
        title="Implement alpha module",
        description="Write the initial alpha module implementation with tests.",
        target_files=["src/alpha.py"],
        acceptance_criteria=["Module imports cleanly", "Unit tests pass"],
    )
    t2 = PlanTask(
        task_id="task_t2",
        title="Implement beta module",
        description="Write the beta module that depends on the alpha module output.",
        target_files=["src/beta.py"],
        acceptance_criteria=["Module imports cleanly", "Integration tests pass"],
        dependencies=["task_t1"],
    )
    return Plan(
        title="Two-Task Chain Plan",
        description="A two-task plan used to verify DAG scheduling and upstream-failure propagation.",
        status=PlanLifecycle.APPROVED,
        approved_at=datetime.now(UTC),
        tasks=[t1, t2],
    )


def test_dag_scheduler_executes_in_topological_order_and_blocks_downstream_on_failure(tmp_path):
    from fiat.execution.scheduler import PlanScheduler

    plan = _two_task_approved_plan()
    exec_store = ExecutionStore(tmp_path)
    execution_order = PlanScheduler.get_execution_order(plan)

    # t1 must precede t2
    assert execution_order.index("task_t1") < execution_order.index("task_t2")

    run = exec_store.create_run(plan, b"{}", execution_order=execution_order)

    # Initial state: t1 QUEUED, t2 BLOCKED_BY_DEPENDENCY
    assert run.task_states["task_t1"] == TaskExecutionState.QUEUED
    assert run.task_states["task_t2"] == TaskExecutionState.BLOCKED_BY_DEPENDENCY

    # Next runnable must be t1
    assert PlanScheduler.next_runnable_task_id(run) == "task_t1"

    # Simulate t1 failing
    run.task_states["task_t1"] = TaskExecutionState.FAILED
    run = PlanScheduler.refresh_task_readiness(plan, run)

    # t2 must now be BLOCKED_UPSTREAM_FAILED
    assert run.task_states["task_t2"] == TaskExecutionState.BLOCKED_UPSTREAM_FAILED

    # No runnable task remains
    assert PlanScheduler.next_runnable_task_id(run) is None

    # Simulate a fresh run where t1 completes — t2 should become QUEUED
    run2 = exec_store.create_run(plan, b"{}", execution_order=execution_order, run_id="run_fresh")
    run2.task_states["task_t1"] = TaskExecutionState.COMPLETED
    run2 = PlanScheduler.refresh_task_readiness(plan, run2)
    assert run2.task_states["task_t2"] == TaskExecutionState.QUEUED
    assert PlanScheduler.next_runnable_task_id(run2) == "task_t2"


def test_crash_recovery_restores_interrupted_running_task_and_resumes_cleanly(tmp_path):
    from fiat.execution.executor import PlanExecutor

    plan = _approved_plan()
    task_id = plan.tasks[0].task_id

    exec_store = ExecutionStore(tmp_path)

    # Seed a file that the task "owns"
    owned = tmp_path / "src" / "feature.py"
    owned.parent.mkdir(parents=True, exist_ok=True)
    owned.write_text("# original\n", encoding="utf-8")

    run = exec_store.create_run(plan, b"{}", execution_order=[task_id])
    exec_store.snapshot_target_files(run.run_id, task_id, ["src/feature.py"])

    # Simulate a crash: task was left RUNNING and the file was mutated
    owned.write_text("# corrupted by crash\n", encoding="utf-8")
    run.task_states[task_id] = TaskExecutionState.RUNNING
    exec_store.save_run(run)

    # Build a minimal executor (task_runner won't be called during recover_run)
    executor = PlanExecutor(
        plan_store=None,
        execution_store=exec_store,
        workspace_manager=None,
        permission_manager=None,
        task_runner=lambda t, r: True,
    )

    recovered_run = executor.recover_run(run.run_id)

    # Task must be RECOVERED and file rolled back to original
    assert recovered_run.task_states[task_id] == TaskExecutionState.RECOVERED
    assert recovered_run.lifecycle == RunLifecycle.RECOVERED
    assert owned.read_text(encoding="utf-8") == "# original\n"

    # next_runnable should now surface the recovered task
    from fiat.execution.scheduler import PlanScheduler
    assert PlanScheduler.next_runnable_task_id(recovered_run) == task_id
