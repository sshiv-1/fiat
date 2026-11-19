from collections.abc import Callable
from datetime import datetime
from typing import Any

from fiat.execution.models import (
    ExecutionRun,
    RunLifecycle,
    TaskAttemptRecord,
    TaskExecutionState,
)
from fiat.execution.scheduler import PlanScheduler
from fiat.execution.store import ExecutionStore
from fiat.execution.verifier import TaskVerifier
from fiat.planning.models import PlanLifecycle


class PlanExecutor:
    def __init__(
        self,
        plan_store: Any,
        execution_store: ExecutionStore,
        workspace_manager: Any,
        permission_manager: Any,
        task_runner: Callable[[Any, str], bool],
        verifier: TaskVerifier | None = None,
    ):
        self.plan_store = plan_store
        self.execution_store = execution_store
        self.workspace_manager = workspace_manager
        self.permission_manager = permission_manager
        self.task_runner = task_runner
        self.verifier = verifier or TaskVerifier()

    def _load_plan_with_bytes(self, plan_id: str) -> tuple[Any, bytes]:
        """Load a plan and return it together with its raw bytes for SHA256 binding."""
        plan = self.plan_store.load(plan_id)
        plan_path = self.plan_store._path_for(plan_id)
        return plan, plan_path.read_bytes()

    def execute_plan(self, plan_id: str, run_id: str | None = None) -> ExecutionRun:
        plan, plan_bytes = self._load_plan_with_bytes(plan_id)

        lifecycle = getattr(plan, "status", None) or getattr(plan, "lifecycle", None)
        if lifecycle != PlanLifecycle.APPROVED:
            raise ValueError("Only APPROVED plans can be executed")

        if run_id:
            run = self.execution_store.load_run(run_id)
            if run.plan_sha256 != self.execution_store.compute_plan_sha256(plan_bytes):
                raise ValueError(
                    "Plan payload has changed since run creation; checksum mismatch"
                )
        else:
            execution_order = PlanScheduler.get_execution_order(plan)
            run = self.execution_store.create_run(
                plan, plan_bytes, execution_order=execution_order
            )

        self.execution_store.acquire_lock(run.run_id, plan_id)
        run.lifecycle = RunLifecycle.RUNNING
        self.execution_store.save_run(run)

        try:
            tasks = getattr(plan, "tasks", [])
            task_map = {
                (t.task_id if hasattr(t, "task_id") else t.id): t for t in tasks
            }

            while True:
                run = PlanScheduler.refresh_task_readiness(plan, run)
                tid = PlanScheduler.next_runnable_task_id(run)
                if not tid:
                    break

                task_obj = task_map.get(tid)
                target_files = (
                    getattr(task_obj, "target_files", []) if task_obj else []
                )

                self.execution_store.snapshot_target_files(run.run_id, tid, target_files)

                run.task_states[tid] = TaskExecutionState.RUNNING
                run.updated_at = datetime.utcnow().isoformat()
                run.summary = self.execution_store.recompute_summary(run.task_states)
                self.execution_store.save_run(run)

                ckpt = self.execution_store.load_checkpoint(run.run_id, tid)
                ckpt.state = TaskExecutionState.RUNNING
                ckpt.attempt_count += 1
                attempt_num = ckpt.attempt_count
                start_time = datetime.utcnow().isoformat()

                success = False
                err_msg = None
                try:
                    success = self.task_runner(task_obj, run.run_id)
                except Exception as exc:
                    success = False
                    err_msg = str(exc)

                evidence = None
                if success:
                    run.task_states[tid] = TaskExecutionState.VERIFYING
                    ckpt.state = TaskExecutionState.VERIFYING
                    self.execution_store.save_checkpoint(ckpt)

                    evidence = self.verifier.verify_task(
                        task_obj, self.execution_store.workspace_root
                    )
                    success = evidence.verified

                end_time = datetime.utcnow().isoformat()
                attempt_record = TaskAttemptRecord(
                    attempt_number=attempt_num,
                    started_at=start_time,
                    ended_at=end_time,
                    state=(
                        TaskExecutionState.COMPLETED
                        if success
                        else TaskExecutionState.FAILED
                    ),
                    verification=evidence,
                    error_message=err_msg,
                )
                ckpt.attempts.append(attempt_record)

                if success:
                    run.task_states[tid] = TaskExecutionState.COMPLETED
                    ckpt.state = TaskExecutionState.COMPLETED
                    ckpt.post_task_file_hashes = {rel: None for rel in target_files}
                else:
                    self.execution_store.restore_target_files(run.run_id, tid)
                    if attempt_num > ckpt.max_retries:
                        run.task_states[tid] = TaskExecutionState.FAILED
                        ckpt.state = TaskExecutionState.FAILED
                    else:
                        run.task_states[tid] = TaskExecutionState.RETRYING
                        ckpt.state = TaskExecutionState.RETRYING

                ckpt.updated_at = end_time
                self.execution_store.save_checkpoint(ckpt)
                run.summary = self.execution_store.recompute_summary(run.task_states)
                self.execution_store.save_run(run)

                if run.task_states[tid] == TaskExecutionState.FAILED:
                    run.lifecycle = RunLifecycle.FAILED
                    self.execution_store.save_run(run)
                    break

            if run.lifecycle == RunLifecycle.RUNNING:
                if any(
                    s == TaskExecutionState.FAILED for s in run.task_states.values()
                ):
                    run.lifecycle = RunLifecycle.FAILED
                else:
                    run.lifecycle = RunLifecycle.COMPLETED
                self.execution_store.save_run(run)

            return run
        finally:
            self.execution_store.release_lock(run.run_id)

    def recover_run(self, run_id: str) -> ExecutionRun:
        run = self.execution_store.load_run(run_id)
        for tid, state in run.task_states.items():
            if state in {
                TaskExecutionState.RUNNING,
                TaskExecutionState.VERIFYING,
                TaskExecutionState.AWAITING_PERMISSION,
            }:
                self.execution_store.restore_target_files(run_id, tid)
                run.task_states[tid] = TaskExecutionState.RECOVERED
        run.lifecycle = RunLifecycle.RECOVERED
        run.updated_at = datetime.utcnow().isoformat()
        run.summary = self.execution_store.recompute_summary(run.task_states)
        self.execution_store.save_run(run)
        return run
