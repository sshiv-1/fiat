"""Terminal-neutral renderers for structured plans."""

from __future__ import annotations

from fiat.planning.models import Plan
from fiat.planning.validation import PlanValidator


def render_plan(plan: Plan) -> str:
    """Render all plan details needed for an informed approval decision."""
    lines = [
        "",
        "IMPLEMENTATION PLAN",
        f"Plan: {plan.title}",
        f"ID: {plan.plan_id}",
        f"Status: {plan.status.value}",
        f"Revision: {plan.revision}",
        "",
        plan.description,
        "",
    ]
    try:
        tasks = PlanValidator.topological_order(plan)
    except ValueError:
        tasks = plan.tasks
    for number, task in enumerate(tasks, start=1):
        lines.extend(
            [
                f"TASK {number:02d} [{task.task_id}] — {task.title}",
                task.description,
                "Dependencies: " + (", ".join(task.dependencies) or "None"),
                "Targets: " + (", ".join(task.target_files) or "None specified"),
                "Acceptance criteria:",
                *[f"  - {criterion}" for criterion in task.acceptance_criteria],
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def render_plan_list(plans: list[Plan]) -> str:
    """Render a compact, deterministic persisted-plan list."""
    if not plans:
        return "No saved plans."
    lines = ["Saved plans:"]
    for plan in plans:
        lines.append(
            f"- {plan.plan_id} [{plan.status.value}] r{plan.revision} — {plan.title}"
        )
    return "\n".join(lines)
