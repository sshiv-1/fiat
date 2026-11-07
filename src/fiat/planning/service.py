"""Lifecycle service for persisted structured plans."""

from __future__ import annotations

from fiat.planning.models import GeneratedPlan, Plan, PlanLifecycle
from fiat.planning.store import PlanStore
from fiat.planning.validation import PlanValidator


class PlanService:
    """Enforces plan validation, transitions, persistence, and approval rules."""

    def __init__(self, store: PlanStore) -> None:
        self.store = store

    def prepare(self, generated: GeneratedPlan, existing: Plan | None = None) -> Plan:
        """Create or refresh a plan and move it to awaiting explicit approval."""
        if existing is None:
            plan = Plan(
                title=generated.title,
                description=generated.description,
                tasks=generated.tasks,
                metadata=generated.metadata,
            )
        else:
            plan = existing.replace_generated_content(generated)
        PlanValidator.validate(plan)
        if plan.status == PlanLifecycle.DRAFT:
            plan = plan.transition_to(PlanLifecycle.VALIDATED)
        if plan.status == PlanLifecycle.REVISION:
            plan = plan.transition_to(PlanLifecycle.VALIDATED)
        plan = plan.transition_to(PlanLifecycle.AWAITING_APPROVAL)
        self.store.save(plan)
        return plan

    def approve(self, plan_id: str) -> Plan:
        plan = self.store.load(plan_id)
        PlanValidator.validate(plan)
        plan = plan.transition_to(PlanLifecycle.APPROVED)
        self.store.save(plan)
        return plan

    def reject(self, plan_id: str) -> Plan:
        return self._transition(plan_id, PlanLifecycle.REJECTED)

    def cancel(self, plan_id: str) -> Plan:
        return self._transition(plan_id, PlanLifecycle.CANCELLED)

    def begin_revision(self, plan_id: str) -> Plan:
        return self._transition(plan_id, PlanLifecycle.REVISION)

    def _transition(self, plan_id: str, target: PlanLifecycle) -> Plan:
        plan = self.store.load(plan_id).transition_to(target)
        self.store.save(plan)
        return plan
