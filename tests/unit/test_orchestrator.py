import json

from fiat.agents.orchestrator import Orchestrator
from fiat.agents.protocol import (
    PlannerResponse,
    ReviewerResponse,
    StructuredOutputError,
    WorkflowStatus,
    parse_structured_response,
)
from fiat.tools.workspace import WorkspaceManager


class FakeProvider:
    def __init__(self, response):
        self.response = response

    def stream(self, _prompt):
        if isinstance(self.response, Exception):
            raise self.response
        yield self.response


class FakeCore:
    def __init__(self, root):
        self.workspace = WorkspaceManager(root)
        self.read_file = lambda *_: ""
        self.list_files = lambda *_: ""
        self.glob_files = lambda *_: ""
        self.grep_search = lambda *_: ""
        self.edit_file = lambda *_: ""
        self.multi_edit = lambda *_: ""
        self.run_command = lambda *_: ""


def response(status, summary="done", **extra):
    return json.dumps({"status": status, "summary": summary, **extra})


def workflow_with_responses(tmp_path, monkeypatch, responses):
    orchestrator = Orchestrator(FakeCore(tmp_path))
    providers = iter(FakeProvider(item) for item in responses)
    monkeypatch.setattr(orchestrator, "_create_agent", lambda *_: next(providers))
    return orchestrator, "".join(orchestrator.run("Improve collision handling"))


def test_structured_parser_rejects_empty_and_not_approved_text():
    for raw in ("", "NOT APPROVED", '{"status":"PASS","summary":""}'):
        try:
            parse_structured_response(raw, ReviewerResponse)
        except StructuredOutputError:
            continue
        raise AssertionError(f"Expected rejected response: {raw!r}")


def test_planner_requires_a_non_empty_validated_plan():
    invalid = '{"status":"PASS","summary":"plan","plan":[]}'

    try:
        parse_structured_response(invalid, PlannerResponse)
    except StructuredOutputError:
        return
    raise AssertionError("Expected planner response with no steps to be rejected")


def test_no_tests_is_not_reported_as_success(tmp_path, monkeypatch):
    orchestrator, output = workflow_with_responses(
        tmp_path,
        monkeypatch,
        [
            '{"workflow":"COMPLEX"}',
            response("PASS", plan=["change code"]),
            response("PASS", files_changed=["pkg/a.py"]),
            response("NO_TESTS", "No test command applies"),
        ],
    )

    assert "not verified" in output
    assert orchestrator.last_state.status == WorkflowStatus.NO_TESTS
    assert orchestrator.last_state.verification_passed is False


def test_malformed_reviewer_cannot_approve_changes(tmp_path, monkeypatch):
    orchestrator, output = workflow_with_responses(
        tmp_path,
        monkeypatch,
        [
            '{"workflow":"COMPLEX"}',
            response("PASS", plan=["change code"]),
            response("PASS", files_changed=["pkg/a.py"]),
            response("PASS", commands=["pytest"]),
            "NOT APPROVED",
        ],
    )

    assert "Reviewer output rejected" in output
    assert orchestrator.last_state.status == WorkflowStatus.BLOCKED
    assert orchestrator.last_state.verification_passed is False


def test_retry_limit_is_enforced_after_failed_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("FIAT_MAX_AGENT_ITERATIONS", "2")
    orchestrator, output = workflow_with_responses(
        tmp_path,
        monkeypatch,
        [
            '{"workflow":"COMPLEX"}',
            response("PASS", plan=["change code"]),
            response("PASS", files_changed=["pkg/a.py"]),
            response("FAIL", "test failed", commands=["pytest"]),
            response("PASS", files_changed=["pkg/a.py"]),
            response("FAIL", "test failed", commands=["pytest"]),
        ],
    )

    assert "Maximum agent iterations (2)" in output
    assert orchestrator.last_state.status == WorkflowStatus.FAIL


def test_success_requires_tester_and_reviewer_pass(tmp_path, monkeypatch):
    orchestrator, output = workflow_with_responses(
        tmp_path,
        monkeypatch,
        [
            '{"workflow":"COMPLEX"}',
            response("PASS", plan=["change code"]),
            response("PASS", files_changed=["pkg/a.py"]),
            response("PASS", commands=["pytest"]),
            response("PASS", findings=[]),
        ],
    )

    assert "implemented and verified successfully" in output
    assert orchestrator.last_state.status == WorkflowStatus.PASS
    assert orchestrator.last_state.verification_passed is True


def test_recorded_core_requires_actual_tester_command_for_pass(tmp_path, monkeypatch):
    core = FakeCore(tmp_path)
    core.command_history = []
    orchestrator = Orchestrator(core)
    responses = iter(
        [
            FakeProvider('{"workflow":"COMPLEX"}'),
            FakeProvider(response("PASS", plan=["change code"])),
            FakeProvider(response("PASS", files_changed=["pkg/a.py"])),
            FakeProvider(response("PASS", commands=["pytest"])),
        ]
    )
    monkeypatch.setattr(orchestrator, "_create_agent", lambda *_: next(responses))

    output = "".join(orchestrator.run("Make a change"))

    assert "without a successful terminal verification command" in output
    assert orchestrator.last_state.status == WorkflowStatus.BLOCKED
