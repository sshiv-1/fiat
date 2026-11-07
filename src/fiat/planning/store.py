"""Atomic JSON persistence for workspace-scoped Fiat plans."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from fiat.planning.models import Plan
from fiat.planning.validation import PlanValidationError, PlanValidator
from fiat.tools.workspace import WorkspaceManager


class PlanStoreError(RuntimeError):
    """Raised when persisted plan state is missing, corrupt, or unsupported."""


class PlanStore:
    """Stores plans in a dedicated `.fiat/plans` workspace state directory."""

    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace
        self.state_directory = workspace.root / ".fiat"
        self.plan_directory = self.state_directory / "plans"

    def save(self, plan: Plan) -> Path:
        """Validate and atomically persist one plan without unsafe deserialization."""
        PlanValidator.validate(plan)
        self.plan_directory.mkdir(parents=True, exist_ok=True)
        destination = self._path_for(plan.plan_id)
        self._atomic_write_json(destination, plan.model_dump(mode="json"))
        return destination

    def load(self, plan_id: str) -> Plan:
        """Load and validate a plan by its stable identifier."""
        destination = self._path_for(plan_id)
        if not destination.is_file():
            raise PlanStoreError(f"Unknown plan ID: {plan_id}")
        try:
            raw = json.loads(destination.read_text(encoding="utf-8"))
            plan = Plan.model_validate(raw)
            PlanValidator.validate(plan)
        except (OSError, json.JSONDecodeError, PlanValidationError, ValidationError) as error:
            raise PlanStoreError(f"Plan data for {plan_id} is corrupt: {error}") from error
        if plan.plan_id != plan_id:
            raise PlanStoreError(f"Plan data for {plan_id} has a mismatched plan ID.")
        if plan.schema_version != 1:
            raise PlanStoreError(
                f"Plan {plan_id} has unsupported schema version {plan.schema_version}."
            )
        return plan

    def list(self) -> list[Plan]:
        """List valid plans newest first, skipping no corrupt data silently."""
        if not self.plan_directory.is_dir():
            return []
        plans: list[Plan] = []
        errors: list[str] = []
        for candidate in sorted(self.plan_directory.glob("*.json")):
            try:
                plans.append(self.load(candidate.stem))
            except PlanStoreError as error:
                errors.append(str(error))
        if errors:
            raise PlanStoreError("; ".join(errors))
        return sorted(plans, key=lambda plan: (plan.updated_at, plan.plan_id), reverse=True)

    def _path_for(self, plan_id: str) -> Path:
        if not plan_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in plan_id):
            raise PlanStoreError("Invalid plan ID.")
        return self.plan_directory / f"{plan_id}.json"

    @staticmethod
    def _atomic_write_json(destination: Path, value: object) -> None:
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(value, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, destination)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)
