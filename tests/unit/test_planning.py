import json

import pytest

from fiat.planning.generator import (
    StructuredPlanGenerationError,
    StructuredPlanGenerator,
)
from fiat.planning.models import (
    GeneratedPlan,
    Plan,
    PlanLifecycle,
    PlanLifecycleError,
    PlanTask,
    TaskType,
)
from fiat.planning.service import PlanService
from fiat.planning.store import PlanStore, PlanStoreError
from fiat.planning.validation import PlanValidationError, PlanValidator
from fiat.tools.workspace import WorkspaceManager


def task(task_id, dependencies=()):
    return PlanTask(
        task_id=task_id,
        title=f"Implement {task_id}",
        description=f"Make the concrete changes required for {task_id}.",
        task_type=TaskType.IMPLEMENTATION,
        dependencies=list(dependencies),
        target_files=[f"src/{task_id}.py"],
        acceptance_criteria=[f"{task_id} has an automated verification."],
    )


def plan(*tasks):
    return Plan(
        plan_id="plan_testing",
        title="Testing plan",
        description="A concrete plan used to validate plan lifecycle behavior.",
        tasks=list(tasks),
    )


def generated(*tasks):
    return GeneratedPlan(
        title="Testing plan",
        description="A concrete plan used to validate plan lifecycle behavior.",
        tasks=list(tasks),
    )


def test_plan_serialization_lifecycle_and_revision_invalidate_approval():
    draft = plan(task("task_one"))
    validated = draft.transition_to(PlanLifecycle.VALIDATED)
    awaiting = validated.transition_to(PlanLifecycle.AWAITING_APPROVAL)
    approved = awaiting.transition_to(PlanLifecycle.APPROVED)

    assert Plan.model_validate_json(approved.model_dump_json()) == approved
    assert approved.approved_at is not None

    revision = approved.transition_to(PlanLifecycle.REVISION)
    assert revision.approved_at is None
    refreshed = revision.replace_generated_content(generated(task("task_two")))
    assert refreshed.revision == 1
    assert refreshed.tasks[0].task_id == "task_two"

    with pytest.raises(PlanLifecycleError):
        draft.transition_to(PlanLifecycle.APPROVED)


def test_plan_validator_orders_dags_deterministically_and_rejects_bad_graphs():
    ordered = PlanValidator.topological_order(
        plan(task("task_b", ("task_a",)), task("task_a"), task("task_c", ("task_a",)))
    )
    assert [item.task_id for item in ordered] == ["task_a", "task_b", "task_c"]

    for invalid in (
        plan(task("task_a", ("task_missing",))),
        plan(task("task_a", ("task_a",))),
        plan(task("task_a", ("task_b",)), task("task_b", ("task_a",))),
        plan(task("task_a"), task("task_a")),
    ):
        with pytest.raises(PlanValidationError):
            PlanValidator.validate(invalid)


def test_plan_store_is_atomic_validates_data_and_rejects_corruption(tmp_path):
    store = PlanStore(WorkspaceManager(tmp_path))
    service = PlanService(store)
    ready = service.prepare(generated(task("task_one")))

    assert store.load(ready.plan_id).status == PlanLifecycle.AWAITING_APPROVAL
    assert [saved.plan_id for saved in store.list()] == [ready.plan_id]

    path = store.plan_directory / f"{ready.plan_id}.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(PlanStoreError, match="corrupt"):
        store.load(ready.plan_id)

    cyclic = plan(task("task_a", ("task_b",)), task("task_b", ("task_a",)))
    with pytest.raises(PlanValidationError):
        store.save(cyclic)


def test_plan_service_requires_validation_and_explicit_approval(tmp_path):
    store = PlanStore(WorkspaceManager(tmp_path))
    service = PlanService(store)
    awaiting = service.prepare(generated(task("task_one")))

    approved = service.approve(awaiting.plan_id)
    assert approved.status == PlanLifecycle.APPROVED
    assert approved.approved_at is not None

    revision = service.begin_revision(awaiting.plan_id)
    assert revision.status == PlanLifecycle.REVISION
    assert revision.approved_at is None


class Provider:
    def __init__(self, payload):
        self.payload = payload

    def stream(self, _prompt):
        yield self.payload


def test_structured_generator_uses_read_only_tools_and_retries_invalid_output(tmp_path):
    calls = []
    payload = json.dumps(
        {
            "title": "Add a feature",
            "description": "Implement the requested feature with a focused test.",
            "tasks": [task("task_one").model_dump(mode="json")],
        }
    )
    responses = iter(["not json", payload])

    def factory(role, prompt, tools):
        calls.append((role, prompt, tools))
        return Provider(next(responses))

    def read_file(_path):
        return ""

    generator = StructuredPlanGenerator(
        WorkspaceManager(tmp_path), factory, [read_file], max_attempts=2
    )
    result = generator.generate("Add a feature")

    assert result.title == "Add a feature"
    assert len(calls) == 2
    assert all(call[0] == "StructuredPlanner" for call in calls)
    assert calls[0][2] == [read_file]
    assert "Repository context" in calls[0][1]


def test_structured_generator_reports_bounded_provider_failures(tmp_path):
    generator = StructuredPlanGenerator(
        WorkspaceManager(tmp_path),
        lambda *_: Provider("not json"),
        [],
        max_attempts=2,
    )

    with pytest.raises(StructuredPlanGenerationError, match="after 2 attempt"):
        generator.generate("Add a feature")
