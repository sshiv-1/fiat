"""Bounded, validated multi-agent orchestration for Fiat."""

from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

from fiat.agents.protocol import (
    CoderResponse,
    PlannerResponse,
    ReviewerResponse,
    RouterResponse,
    StructuredOutputError,
    TesterResponse,
    WorkflowStatus,
    parse_structured_response,
)
from fiat.config import get_credential, load_config
from fiat.provider_factory import ProviderFactory
from fiat.state import session_state


class AgentProviderError(RuntimeError):
    """Raised when a provider cannot be configured or streamed."""


def _max_iterations() -> int:
    try:
        requested = int(os.getenv("FIAT_MAX_AGENT_ITERATIONS", "3"))
    except ValueError:
        requested = 3
    return min(max(requested, 1), 10)


@dataclass
class AgentWorkflowState:
    """State retained for a workflow even if a later agent blocks."""

    user_request: str
    plan: PlannerResponse | None = None
    current_task: str = ""
    completed_tasks: list[str] = field(default_factory=list)
    files_inspected: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    test_results: list[TesterResponse] = field(default_factory=list)
    review_findings: list[ReviewerResponse] = field(default_factory=list)
    repository_context: str = ""
    iteration_count: int = 1
    max_iterations: int = field(default_factory=_max_iterations)
    status: WorkflowStatus = WorkflowStatus.PENDING
    verification_passed: bool = False
    error: str | None = None


def get_provider_for_agent(agent_name: str, system_prompt: str, tools: list[Any]) -> Any:
    """Create an existing provider adapter for one specialist role."""
    del agent_name
    config = load_config()
    if config is None:
        raise AgentProviderError("Fiat provider configuration was not found.")
    api_key = get_credential(config.provider_name)
    if not api_key:
        raise AgentProviderError(f"No credential found for {config.provider_name}.")
    provider = ProviderFactory.create(config.provider_name, system_prompt)
    if not provider:
        raise AgentProviderError(f"Unknown provider: {config.provider_name}")
    provider.configure(model=config.model_name, api_key=api_key)
    if tools:
        provider.set_tools(tools)
    return provider


class Orchestrator:
    """Runs a repository-aware workflow whose success requires verification."""

    def __init__(self, core: Any) -> None:
        self.core = core
        self.last_state: AgentWorkflowState | None = None

    def _create_agent(self, role: str, prompt: str, tools: list[Any]) -> Any:
        return get_provider_for_agent(role, prompt, tools)

    @staticmethod
    def _collect(provider: Any, prompt: str) -> str:
        try:
            return "".join(str(chunk) for chunk in provider.stream(prompt))
        except Exception as error:
            raise AgentProviderError(str(error)) from error

    def _repository_context(self, user_request: str) -> str:
        workspace = getattr(self.core, "workspace", None)
        if workspace is None:
            return ""
        try:
            from fiat.repository.context_builder import ContextBuilder

            return ContextBuilder(workspace).build(user_request).as_prompt()
        except Exception as error:
            return f"Repository context unavailable: {error}"

    @staticmethod
    def _update_session(state: AgentWorkflowState, role: str, status: str) -> None:
        session_state.current_role = role
        session_state.agent_status = status
        session_state.current_iteration = state.iteration_count
        session_state.max_iterations = state.max_iterations

    def _finish(self, state: AgentWorkflowState) -> None:
        self.last_state = state
        session_state.current_role = "-"
        session_state.agent_status = (
            "Complete" if state.status == WorkflowStatus.PASS else state.status.value.title()
        )

    def _block(self, state: AgentWorkflowState, message: str) -> Generator[str, None, None]:
        state.status = WorkflowStatus.BLOCKED
        state.error = message
        self._finish(state)
        yield f"\nFiat: Workflow blocked: {message}\n"

    def run(self, user_input: str) -> Generator[str, None, None]:
        """Run direct assistance or a verified, bounded coding workflow."""
        state = AgentWorkflowState(user_request=user_input)
        self.last_state = state
        ro_tools = [
            self.core.read_file,
            self.core.list_files,
            self.core.glob_files,
            self.core.grep_search,
        ]
        rw_tools = ro_tools + [
            self.core.edit_file,
            self.core.multi_edit,
            self.core.run_command,
        ]
        test_tools = [self.core.run_command]
        state.status = WorkflowStatus.IN_PROGRESS
        self._update_session(state, "Orchestrator", "Running")
        yield "[Orchestrator] Retrieving repository context...\n"
        state.repository_context = self._repository_context(user_input)

        router_prompt = (
            "Classify the request. Return JSON only: "
            '{"workflow":"SIMPLE"} for a non-modifying conversational response or '
            '{"workflow":"COMPLEX"} for any repository inspection, code, test, or edit task.'
        )
        try:
            router = self._create_agent("Orchestrator", router_prompt, [])
            route = parse_structured_response(
                self._collect(router, user_input), RouterResponse
            )
        except (AgentProviderError, StructuredOutputError):
            route = RouterResponse(workflow="COMPLEX")

        if route.workflow == "SIMPLE":
            try:
                responder = self._create_agent(
                    "Responder",
                    "Answer the user directly. Do not modify files or run commands.",
                    [],
                )
                response = self._collect(responder, user_input)
            except AgentProviderError as error:
                yield from self._block(state, str(error))
                return
            if not response.strip():
                yield from self._block(state, "Direct responder returned an empty response.")
                return
            state.status = WorkflowStatus.PASS
            self._finish(state)
            yield response
            return

        yield "[Planner] Creating a validated plan...\n"
        planner_prompt = (
            "You are the Planner. Inspect the repository with read-only tools and return "
            "JSON only in this exact shape: "
            '{"status":"PASS|BLOCKED|CANCELLED","summary":"...","plan":["..."]}. '
            "A plan must be concrete and non-empty.\n"
            f"User request: {state.user_request}\n"
            f"Repository context:\n{state.repository_context}"
        )
        try:
            planner = self._create_agent("Planner", planner_prompt, ro_tools)
            state.plan = parse_structured_response(
                self._collect(planner, "Create the implementation plan."), PlannerResponse
            )
        except (AgentProviderError, StructuredOutputError) as error:
            yield from self._block(state, f"Planner output rejected: {error}")
            return
        if state.plan.status != WorkflowStatus.PASS:
            state.status = state.plan.status
            self._finish(state)
            yield f"\nFiat: Planning ended with {state.status.value}. {state.plan.summary}\n"
            return

        while state.iteration_count <= state.max_iterations:
            self._update_session(state, "Coder", "Running")
            yield (
                f"[Coder] Implementing iteration {state.iteration_count}/"
                f"{state.max_iterations}...\n"
            )
            coder_prompt = (
                "You are the Coder. Execute the approved plan with your tools. Return JSON "
                "only: {\"status\":\"PASS|FAIL|BLOCKED|CANCELLED\","
                '"summary":"...","files_changed":["path"]}. A PASS means work was '
                "attempted; it is not verification.\n"
                f"User request: {state.user_request}\n"
                f"Plan: {state.plan.model_dump_json()}\n"
                f"Prior test results: {[item.model_dump() for item in state.test_results]}\n"
                f"Prior reviews: {[item.model_dump() for item in state.review_findings]}"
            )
            try:
                coder = self._create_agent("Coder", coder_prompt, rw_tools)
                coder_result = parse_structured_response(
                    self._collect(coder, "Implement the plan or address prior findings."),
                    CoderResponse,
                )
            except (AgentProviderError, StructuredOutputError) as error:
                yield from self._block(state, f"Coder output rejected: {error}")
                return
            state.files_modified.extend(coder_result.files_changed)
            if coder_result.status != WorkflowStatus.PASS:
                state.status = coder_result.status
                self._finish(state)
                yield f"\nFiat: Implementation ended with {state.status.value}.\n"
                return

            self._update_session(state, "Tester", "Running")
            yield "[Tester] Running verification...\n"
            command_history = getattr(self.core, "command_history", None)
            history_start = len(command_history) if isinstance(command_history, list) else 0
            tester_prompt = (
                "You are the Tester. Run relevant tests with run_command. Return JSON only: "
                '{"status":"PASS|FAIL|BLOCKED|NO_TESTS|CANCELLED",'
                '"summary":"actual result","commands":["..."]}. '
                "NO_TESTS is never PASS; only report PASS after an actual command succeeds.\n"
                f"User request: {state.user_request}\nPlan: {state.plan.model_dump_json()}"
            )
            try:
                tester = self._create_agent("Tester", tester_prompt, test_tools)
                tester_result = parse_structured_response(
                    self._collect(tester, "Run relevant verification now."), TesterResponse
                )
            except (AgentProviderError, StructuredOutputError) as error:
                yield from self._block(state, f"Tester output rejected: {error}")
                return
            state.test_results.append(tester_result)
            if tester_result.status == WorkflowStatus.NO_TESTS:
                state.status = WorkflowStatus.NO_TESTS
                self._finish(state)
                yield "\nFiat: No tests were found; implementation is not verified.\n"
                return
            if tester_result.status in {WorkflowStatus.BLOCKED, WorkflowStatus.CANCELLED}:
                state.status = tester_result.status
                self._finish(state)
                yield f"\nFiat: Testing ended with {state.status.value}.\n"
                return
            if tester_result.status == WorkflowStatus.FAIL:
                yield "[Tester] Verification failed; retrying implementation.\n"
                state.iteration_count += 1
                continue
            if isinstance(command_history, list) and not self._has_test_evidence(
                command_history[history_start:]
            ):
                yield from self._block(
                    state,
                    "Tester reported PASS without a successful terminal verification command.",
                )
                return

            self._update_session(state, "Reviewer", "Running")
            yield "[Reviewer] Reviewing verified implementation...\n"
            reviewer_prompt = (
                "You are the Reviewer. Inspect the repository with read-only tools. Return "
                "JSON only: {\"status\":\"PASS|FAIL|BLOCKED|CANCELLED\","
                '"summary":"...","findings":["..."]}. '
                "Use PASS only when requirements are met. The phrase NOT APPROVED is not PASS.\n"
                f"User request: {state.user_request}\n"
                f"Plan: {state.plan.model_dump_json()}\n"
                f"Test result: {tester_result.model_dump_json()}"
            )
            try:
                reviewer = self._create_agent("Reviewer", reviewer_prompt, ro_tools)
                reviewer_result = parse_structured_response(
                    self._collect(reviewer, "Review the current implementation."),
                    ReviewerResponse,
                )
            except (AgentProviderError, StructuredOutputError) as error:
                yield from self._block(state, f"Reviewer output rejected: {error}")
                return
            state.review_findings.append(reviewer_result)
            if reviewer_result.status == WorkflowStatus.PASS:
                state.status = WorkflowStatus.PASS
                state.verification_passed = True
                self._finish(state)
                yield "\nFiat: Task implemented and verified successfully.\n"
                return
            if reviewer_result.status in {WorkflowStatus.BLOCKED, WorkflowStatus.CANCELLED}:
                state.status = reviewer_result.status
                self._finish(state)
                yield f"\nFiat: Review ended with {state.status.value}.\n"
                return
            yield "[Reviewer] Issues found; retrying implementation.\n"
            state.iteration_count += 1

        state.status = WorkflowStatus.FAIL
        self._finish(state)
        yield (
            f"\nFiat: Maximum agent iterations ({state.max_iterations}) reached; "
            "the task is not verified.\n"
        )

    @staticmethod
    def _has_test_evidence(records: list[tuple[str, Any]]) -> bool:
        """Require a successful command issued while the tester role was active."""
        return any(
            role == "Tester"
            and getattr(result, "status", None) == "completed"
            and getattr(result, "exit_code", None) == 0
            for role, result in records
        )
