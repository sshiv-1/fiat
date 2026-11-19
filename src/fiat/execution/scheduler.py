from typing import Any

from fiat.execution.models import ExecutionRun, TaskExecutionState
from fiat.planning.validation import PlanValidator


class PlanScheduler:
    @staticmethod
    def get_execution_order(plan: Any) -> list[str]:
        ordered_tasks = PlanValidator.topological_order(plan)
        return [t.task_id if hasattr(t, "task_id") else t.id for t in ordered_tasks]

    @staticmethod
    def refresh_task_readiness(plan: Any, run: ExecutionRun) -> ExecutionRun:
        tasks = getattr(plan, "tasks", [])
        task_map = {t.task_id if hasattr(t, "task_id") else t.id: t for t in tasks}

        terminal_states = {
            TaskExecutionState.COMPLETED,
            TaskExecutionState.FAILED,
            TaskExecutionState.CANCELLED,
            TaskExecutionState.BLOCKED_UPSTREAM_FAILED
        }

        for tid in run.execution_order:
            current_state = run.task_states.get(tid)
            if current_state in terminal_states:
                continue

            t_obj = task_map.get(tid)
            deps = getattr(t_obj, "dependencies", []) if t_obj else []

            if not deps:
                if current_state == TaskExecutionState.BLOCKED_BY_DEPENDENCY:
                    run.task_states[tid] = TaskExecutionState.QUEUED
                continue

            # Check dependencies
            upstream_failed = False
            all_completed = True

            for dep in deps:
                dep_state = run.task_states.get(dep)
                if dep_state in {TaskExecutionState.FAILED, TaskExecutionState.CANCELLED, TaskExecutionState.BLOCKED_UPSTREAM_FAILED}:
                    upstream_failed = True
                    break
                if dep_state != TaskExecutionState.COMPLETED:
                    all_completed = False

            if upstream_failed:
                run.task_states[tid] = TaskExecutionState.BLOCKED_UPSTREAM_FAILED
            elif all_completed and current_state == TaskExecutionState.BLOCKED_BY_DEPENDENCY:
                run.task_states[tid] = TaskExecutionState.QUEUED

        return run

    @staticmethod
    def next_runnable_task_id(run: ExecutionRun) -> str | None:
        for tid in run.execution_order:
            state = run.task_states.get(tid)
            if state in {TaskExecutionState.QUEUED, TaskExecutionState.RECOVERED}:
                return tid
        return None
