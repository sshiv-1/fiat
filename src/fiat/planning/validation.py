"""Provider-independent structural validation for implementation plans."""

from __future__ import annotations

import heapq
from collections.abc import Iterable

from fiat.planning.models import Plan, PlanTask, TaskLifecycle


class PlanValidationError(ValueError):
    """Raised with all structural errors found in one plan validation pass."""

    def __init__(self, issues: Iterable[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


class PlanValidator:
    """Validates plan DAGs and produces deterministic implementation ordering."""

    @classmethod
    def validate(cls, plan: Plan) -> None:
        issues = cls.issues(plan)
        if issues:
            raise PlanValidationError(issues)

    @classmethod
    def issues(cls, plan: Plan) -> list[str]:
        issues: list[str] = []
        if plan.schema_version != 1:
            issues.append(f"Unsupported plan schema version: {plan.schema_version}.")
        if not plan.tasks:
            issues.append("Plan must contain at least one task.")
            return issues
        task_ids = [task.task_id for task in plan.tasks]
        duplicate_ids = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
        for task_id in duplicate_ids:
            issues.append(f"Duplicate task ID: {task_id}.")
        known_ids = set(task_ids)
        for task in plan.tasks:
            issues.extend(cls._task_issues(task, known_ids))
        if not issues:
            try:
                cls.topological_order(plan)
            except PlanValidationError as error:
                issues.extend(error.issues)
        return issues

    @staticmethod
    def _task_issues(task: PlanTask, known_ids: set[str]) -> list[str]:
        issues: list[str] = []
        if task.status not in set(TaskLifecycle):
            issues.append(f"Task {task.task_id} has an invalid status.")
        if not task.title.strip() or not task.description.strip():
            issues.append(f"Task {task.task_id} is missing a meaningful title or description.")
        if not task.acceptance_criteria:
            issues.append(f"Task {task.task_id} has no acceptance criteria.")
        if not task.target_files:
            issues.append(f"Task {task.task_id} has no expected target files or modules.")
        for dependency in task.dependencies:
            if dependency == task.task_id:
                issues.append(f"Task {task.task_id} cannot depend on itself.")
            elif dependency not in known_ids:
                issues.append(
                    f"Task {task.task_id} depends on unknown task {dependency}."
                )
        return issues

    @classmethod
    def topological_order(cls, plan: Plan) -> list[PlanTask]:
        """Return tasks in stable dependency order or raise on a malformed DAG."""
        task_by_id = {task.task_id: task for task in plan.tasks}
        if len(task_by_id) != len(plan.tasks):
            raise PlanValidationError(["Task IDs must be unique before ordering."])
        sequence = {task.task_id: index for index, task in enumerate(plan.tasks)}
        remaining = {task.task_id: len(task.dependencies) for task in plan.tasks}
        dependents: dict[str, list[str]] = {task.task_id: [] for task in plan.tasks}
        for task in plan.tasks:
            for dependency in task.dependencies:
                if dependency not in task_by_id:
                    raise PlanValidationError(
                        [f"Task {task.task_id} depends on unknown task {dependency}."]
                    )
                if dependency == task.task_id:
                    raise PlanValidationError([f"Task {task.task_id} cannot depend on itself."])
                dependents[dependency].append(task.task_id)
        ready = [(sequence[task.task_id], task.task_id) for task in plan.tasks if not task.dependencies]
        heapq.heapify(ready)
        ordered: list[PlanTask] = []
        while ready:
            _, task_id = heapq.heappop(ready)
            ordered.append(task_by_id[task_id])
            for dependent_id in sorted(dependents[task_id], key=sequence.__getitem__):
                remaining[dependent_id] -= 1
                if remaining[dependent_id] == 0:
                    heapq.heappush(ready, (sequence[dependent_id], dependent_id))
        if len(ordered) != len(plan.tasks):
            blocked = sorted(task_id for task_id, count in remaining.items() if count > 0)
            raise PlanValidationError(
                ["Circular task dependencies prevent ordering: " + ", ".join(blocked) + "."]
            )
        return ordered
