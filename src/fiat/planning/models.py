"""Pydantic domain models for approval-gated implementation plans."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

PLAN_SCHEMA_VERSION = 1


class PlanLifecycle(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    REVISION = "REVISION"


class TaskLifecycle(StrEnum):
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskType(StrEnum):
    ANALYSIS = "ANALYSIS"
    IMPLEMENTATION = "IMPLEMENTATION"
    TESTING = "TESTING"
    DOCUMENTATION = "DOCUMENTATION"
    CONFIGURATION = "CONFIGURATION"
    REVIEW = "REVIEW"


class PlanLifecycleError(ValueError):
    """Raised when a plan lifecycle transition is not allowed."""


_ALLOWED_TRANSITIONS: dict[PlanLifecycle, frozenset[PlanLifecycle]] = {
    PlanLifecycle.DRAFT: frozenset({PlanLifecycle.VALIDATED, PlanLifecycle.CANCELLED}),
    PlanLifecycle.VALIDATED: frozenset(
        {
            PlanLifecycle.AWAITING_APPROVAL,
            PlanLifecycle.REJECTED,
            PlanLifecycle.CANCELLED,
            PlanLifecycle.REVISION,
        }
    ),
    PlanLifecycle.AWAITING_APPROVAL: frozenset(
        {
            PlanLifecycle.APPROVED,
            PlanLifecycle.REJECTED,
            PlanLifecycle.CANCELLED,
            PlanLifecycle.REVISION,
        }
    ),
    PlanLifecycle.APPROVED: frozenset(
        {PlanLifecycle.REVISION, PlanLifecycle.CANCELLED}
    ),
    PlanLifecycle.REJECTED: frozenset({PlanLifecycle.REVISION, PlanLifecycle.CANCELLED}),
    PlanLifecycle.REVISION: frozenset({PlanLifecycle.VALIDATED, PlanLifecycle.CANCELLED}),
    PlanLifecycle.CANCELLED: frozenset(),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _plan_id() -> str:
    return f"plan_{uuid4().hex[:12]}"


def _task_id() -> str:
    return f"task_{uuid4().hex[:10]}"


class PlanTask(BaseModel):
    """One dependency-aware unit of a future implementation plan."""

    task_id: str = Field(default_factory=_task_id, min_length=3, max_length=80)
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=4_000)
    task_type: TaskType = TaskType.IMPLEMENTATION
    status: TaskLifecycle = TaskLifecycle.PENDING
    dependencies: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.replace("_", "").replace("-", "").isalnum():
            raise ValueError("task_id may contain only letters, digits, underscores, and hyphens")
        return normalized

    @field_validator("title", "description")
    @classmethod
    def require_meaningful_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized

    @field_validator("dependencies", "target_files", "acceptance_criteria")
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("list values must not contain duplicates")
        return normalized


class GeneratedPlan(BaseModel):
    """The provider-owned portion of a structured implementation plan."""

    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=4_000)
    tasks: list[PlanTask] = Field(min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "description")
    @classmethod
    def require_meaningful_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized


class Plan(BaseModel):
    """A persisted plan with explicit lifecycle and approval metadata."""

    schema_version: int = Field(default=PLAN_SCHEMA_VERSION, ge=1)
    plan_id: str = Field(default_factory=_plan_id, min_length=8, max_length=80)
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=4_000)
    status: PlanLifecycle = PlanLifecycle.DRAFT
    tasks: list[PlanTask] = Field(min_length=1, max_length=100)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    approved_at: datetime | None = None
    revision: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.replace("_", "").replace("-", "").isalnum():
            raise ValueError("plan_id may contain only letters, digits, underscores, and hyphens")
        return normalized

    @field_validator("title", "description")
    @classmethod
    def require_meaningful_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_approval_timestamp(self) -> Plan:
        if self.status == PlanLifecycle.APPROVED and self.approved_at is None:
            raise ValueError("approved plans must record an approval timestamp")
        if self.status != PlanLifecycle.APPROVED and self.approved_at is not None:
            raise ValueError("only approved plans may retain an approval timestamp")
        return self

    def transition_to(self, target: PlanLifecycle) -> Plan:
        """Return a lifecycle-safe copy of this plan in ``target`` state."""
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise PlanLifecycleError(
                f"Cannot transition plan {self.plan_id} from {self.status.value} "
                f"to {target.value}."
            )
        approved_at = _now() if target == PlanLifecycle.APPROVED else self.approved_at
        if target == PlanLifecycle.REVISION:
            approved_at = None
        return self.model_copy(
            update={"status": target, "updated_at": _now(), "approved_at": approved_at}
        )

    def replace_generated_content(self, generated: GeneratedPlan) -> Plan:
        """Replace a revision's content and invalidate any prior approval."""
        if self.status != PlanLifecycle.REVISION:
            raise PlanLifecycleError("Plan content can only be replaced during REVISION.")
        return self.model_copy(
            update={
                "title": generated.title,
                "description": generated.description,
                "tasks": generated.tasks,
                "metadata": generated.metadata,
                "revision": self.revision + 1,
                "approved_at": None,
                "updated_at": _now(),
            }
        )
