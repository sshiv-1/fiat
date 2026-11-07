"""Validated response contracts for Fiat's multi-agent workflow."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel, Field, field_validator


class WorkflowStatus(StrEnum):
    """The only states used to decide workflow progress and completion."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NO_TESTS = "NO_TESTS"
    CANCELLED = "CANCELLED"


class StructuredOutputError(ValueError):
    """Raised when an agent response is empty, malformed, or invalid."""


class RouterResponse(BaseModel):
    """A constrained decision about whether a request needs the full workflow."""

    workflow: str

    @field_validator("workflow")
    @classmethod
    def validate_workflow(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"SIMPLE", "COMPLEX"}:
            raise ValueError("workflow must be SIMPLE or COMPLEX")
        return normalized


class PlannerResponse(BaseModel):
    """A validated repository-aware implementation plan."""

    status: WorkflowStatus
    summary: str = Field(min_length=1)
    plan: list[str] = Field(min_length=1)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: WorkflowStatus) -> WorkflowStatus:
        if value not in {
            WorkflowStatus.PASS,
            WorkflowStatus.BLOCKED,
            WorkflowStatus.CANCELLED,
        }:
            raise ValueError("planner status must be PASS, BLOCKED, or CANCELLED")
        return value

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be empty")
        return value.strip()

    @field_validator("plan")
    @classmethod
    def non_empty_steps(cls, value: list[str]) -> list[str]:
        steps = [step.strip() for step in value if step.strip()]
        if not steps:
            raise ValueError("plan must contain at least one non-empty step")
        return steps


class CoderResponse(BaseModel):
    """A status report from the implementation agent, not a verification result."""

    status: WorkflowStatus
    summary: str = Field(min_length=1)
    files_changed: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: WorkflowStatus) -> WorkflowStatus:
        if value not in {
            WorkflowStatus.PASS,
            WorkflowStatus.FAIL,
            WorkflowStatus.BLOCKED,
            WorkflowStatus.CANCELLED,
        }:
            raise ValueError("coder status must be PASS, FAIL, BLOCKED, or CANCELLED")
        return value

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be empty")
        return value.strip()


class TesterResponse(BaseModel):
    """A verification result whose NO_TESTS state never means success."""

    status: WorkflowStatus
    summary: str = Field(min_length=1)
    commands: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: WorkflowStatus) -> WorkflowStatus:
        if value not in {
            WorkflowStatus.PASS,
            WorkflowStatus.FAIL,
            WorkflowStatus.BLOCKED,
            WorkflowStatus.NO_TESTS,
            WorkflowStatus.CANCELLED,
        }:
            raise ValueError(
                "tester status must be PASS, FAIL, BLOCKED, NO_TESTS, or CANCELLED"
            )
        return value

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be empty")
        return value.strip()


class ReviewerResponse(BaseModel):
    """A review decision that can only approve with explicit PASS JSON."""

    status: WorkflowStatus
    summary: str = Field(min_length=1)
    findings: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: WorkflowStatus) -> WorkflowStatus:
        if value not in {
            WorkflowStatus.PASS,
            WorkflowStatus.FAIL,
            WorkflowStatus.BLOCKED,
            WorkflowStatus.CANCELLED,
        }:
            raise ValueError("reviewer status must be PASS, FAIL, BLOCKED, or CANCELLED")
        return value

    @field_validator("summary")
    @classmethod
    def non_empty_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be empty")
        return value.strip()


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def parse_structured_response(raw: str, model_type: type[ResponseModel]) -> ResponseModel:
    """Extract and validate one JSON object from a streamed model response."""
    if not raw or not raw.strip():
        raise StructuredOutputError("Agent returned an empty response.")
    candidates = [raw.strip()]
    candidates.extend(match.group(1) for match in _FENCED_JSON.finditer(raw))
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(json.dumps(value))
    for candidate in candidates:
        try:
            return model_type.model_validate_json(candidate)
        except (ValueError, TypeError):
            continue
    raise StructuredOutputError(
        f"Agent response is not valid {model_type.__name__} JSON."
    )
