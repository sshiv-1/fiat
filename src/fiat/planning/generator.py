"""Provider-agnostic generation of validated, repository-aware plans."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fiat.planning.models import GeneratedPlan, Plan
from fiat.repository.context_builder import ContextBuilder
from fiat.tools.workspace import WorkspaceManager


class StructuredPlanGenerationError(RuntimeError):
    """Raised after bounded structured-output generation retries are exhausted."""


ProviderFactory = Callable[[str, str, list[Any]], Any]


class StructuredPlanGenerator:
    """Builds plans with read-only tools and explicit Pydantic validation."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        provider_factory: ProviderFactory,
        read_only_tools: list[Any],
        max_attempts: int = 2,
    ) -> None:
        self.workspace = workspace
        self.provider_factory = provider_factory
        self.read_only_tools = read_only_tools
        self.max_attempts = max(1, min(max_attempts, 3))

    def generate(self, request: str, revision_of: Plan | None = None) -> GeneratedPlan:
        """Generate a valid plan payload, retrying malformed provider output once."""
        context = ContextBuilder(self.workspace).build(request)
        context_metadata = context.metadata()
        errors: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            prompt = self._system_prompt(request, context.as_prompt(), revision_of, attempt)
            try:
                provider = self.provider_factory("StructuredPlanner", prompt, self.read_only_tools)
                raw = "".join(str(chunk) for chunk in provider.stream("Generate the plan now."))
                generated = self._parse(raw)
                generated.metadata = {**generated.metadata, "repository_context": context_metadata}
                return generated
            except Exception as error:
                errors.append(f"attempt {attempt}: {error}")
        raise StructuredPlanGenerationError(
            "Structured plan generation failed after "
            f"{self.max_attempts} attempt(s): {'; '.join(errors)}"
        )

    @staticmethod
    def _parse(raw: str) -> GeneratedPlan:
        if not raw or not raw.strip():
            raise ValueError("provider returned an empty plan response")
        decoder = json.JSONDecoder()
        value, end = decoder.raw_decode(raw.lstrip())
        if raw.lstrip()[end:].strip():
            raise ValueError("provider response must contain exactly one JSON object")
        if not isinstance(value, dict):
            raise ValueError("provider response must be a JSON object")
        return GeneratedPlan.model_validate(value)

    @staticmethod
    def _system_prompt(
        request: str,
        context: str,
        revision_of: Plan | None,
        attempt: int,
    ) -> str:
        revision = ""
        if revision_of is not None:
            revision = (
                "Revise this existing plan while retaining its plan ID outside the response:\n"
                f"{revision_of.model_dump_json()}\n"
            )
        retry = ""
        if attempt > 1:
            retry = "Your prior response was invalid. Return one complete JSON object and no prose.\n"
        return (
            "You are Fiat's structured planning specialist. Plan Mode is read-only: "
            "use only the provided read tools; do not edit files, run commands, or request execution. "
            "Return exactly one JSON object matching this schema: "
            '{"title":"...","description":"...","tasks":[{"task_id":"task_...",'
            '"title":"...","description":"...","task_type":"ANALYSIS|IMPLEMENTATION|TESTING|DOCUMENTATION|CONFIGURATION|REVIEW",'
            '"status":"PENDING","dependencies":["task_..."],"target_files":["path"],'
            '"acceptance_criteria":["measurable result"]}],"metadata":{}}. '
            "Each task needs concrete targets and measurable acceptance criteria. "
            "Dependencies must form a DAG.\n"
            f"User request:\n{request}\n{revision}{retry}Repository context:\n{context}"
        )
