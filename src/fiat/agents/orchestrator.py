from fiat.state import session_state
from fiat.provider_factory import ProviderFactory
from fiat.config import load_config, get_credential
import os

class AgentWorkflowState:
    def __init__(self, user_request: str):
        self.user_request = user_request
        self.plan = ""
        self.current_task = ""
        self.completed_tasks = []
        self.files_inspected = []
        self.files_modified = []
        self.test_results = []
        self.review_findings = []
        self.iteration_count = 1
        self.max_iterations = int(os.getenv("FIAT_MAX_AGENT_ITERATIONS", "3"))
        self.status = "orchestrating"

def get_provider_for_agent(agent_name: str, system_prompt: str, tools: list):
    config = load_config()
    api_key = get_credential(config.provider_name)
    provider = ProviderFactory.create(config.provider_name, system_prompt)
    if not provider:
        raise ValueError(f"Unknown provider: {config.provider_name}")
    provider.configure(model=config.model_name, api_key=api_key)
    if tools:
        provider.set_tools(tools)
    return provider

class Orchestrator:
    def __init__(self, core):
        self.core = core
        
    def _create_agent(self, role: str, prompt: str, tools: list):
        return get_provider_for_agent(role, prompt, tools)

    def run(self, user_input: str):
        state = AgentWorkflowState(user_input)
        
        # Read-only tools
        ro_tools = [self.core.read_file, self.core.list_files, self.core.glob_files, self.core.grep_search]
        # Write tools
        rw_tools = ro_tools + [self.core.edit_file, self.core.multi_edit, self.core.run_command]
        # Tester tools
        test_tools = [self.core.run_command]

        # 1. Orchestrator analysis
        yield "[Orchestrator] Analyzing request...\n"
        session_state.current_role = "Orchestrator"
        session_state.agent_status = "Running"
        session_state.current_iteration = state.iteration_count
        session_state.max_iterations = state.max_iterations

        orch_prompt = """You are the Orchestrator. 
Analyze the user's request. Does it require a multi-step coding workflow (planning, coding, testing, reviewing)? 
Respond with exactly one word: 'COMPLEX' or 'SIMPLE'.
If SIMPLE, you will just handle it directly. If COMPLEX, we will use the multi-agent workflow."""

        orch_provider = self._create_agent("Orchestrator", orch_prompt, [])
        orch_resp = ""
        for chunk in orch_provider.stream(user_input):
            orch_resp += chunk
            
        if "COMPLEX" not in orch_resp.upper():
            yield "[Orchestrator] Direct execution...\n"
            # Simple flow: act as Coder directly
            coder_prompt = "You are a coding assistant. Fulfill the user's request. You have full tools."
            coder_provider = self._create_agent("Coder", coder_prompt, rw_tools)
            for chunk in coder_provider.stream(user_input):
                yield chunk
            session_state.agent_status = "Complete"
            session_state.current_role = "—"
            return

        # COMPLEX FLOW
        # Planner
        yield "\n[Planner] Analyzing repository and creating plan...\n"
        session_state.current_role = "Planner"
        planner_prompt = f"""You are the Planner.
User request: {state.user_request}
Your job is to inspect the repository using your read-only tools and produce a concise implementation plan.
Output the plan clearly numbered."""
        planner = self._create_agent("Planner", planner_prompt, ro_tools)
        for chunk in planner.stream(f"Create a plan for: {state.user_request}"):
            state.plan += chunk
            
        yield "[Planner] Plan created.\n"

        while state.iteration_count <= state.max_iterations:
            session_state.current_iteration = state.iteration_count
            
            # Coder
            yield f"\n[Coder] Implementing changes (Iteration {state.iteration_count}/{state.max_iterations})...\n"
            session_state.current_role = "Coder"
            coder_prompt = f"""You are the Coder.
User request: {state.user_request}
Plan: {state.plan}
Test results (if any): {state.test_results}
Review findings (if any): {state.review_findings}

Implement the necessary changes using your tools. Do not ask for permission, use the tools.
Once done, reply 'DONE'."""
            coder = self._create_agent("Coder", coder_prompt, rw_tools)
            coder_out = ""
            for chunk in coder.stream("Please implement the next steps or fixes."):
                coder_out += chunk
            
            # Tester
            yield "\n[Tester] Running tests...\n"
            session_state.current_role = "Tester"
            tester_prompt = f"""You are the Tester.
User request: {state.user_request}
Your job is to run tests to validate the Coder's changes.
Use run_command to execute tests (e.g., pytest, npm test, etc) if applicable. 
If no tests are applicable, just say 'NO_TESTS'.
If tests pass, say 'PASS'. If they fail, say 'FAIL' and explain."""
            tester = self._create_agent("Tester", tester_prompt, test_tools)
            tester_out = ""
            for chunk in tester.stream("Run relevant tests and report."):
                tester_out += chunk
            state.test_results.append(tester_out)
            
            if "FAIL" in tester_out.upper():
                yield "[Tester] Failures detected. Sending back to Coder.\n"
                state.iteration_count += 1
                continue

            # Reviewer
            yield "\n[Reviewer] Reviewing implementation...\n"
            session_state.current_role = "Reviewer"
            reviewer_prompt = f"""You are the Reviewer.
User request: {state.user_request}
Plan: {state.plan}
Test output: {tester_out}
Your job is to inspect the codebase to verify the implementation. 
If it is correct, reply exactly 'APPROVED'. 
If there are blocking bugs or missing requirements, reply 'REJECTED' and list the issues."""
            reviewer = self._create_agent("Reviewer", reviewer_prompt, ro_tools)
            reviewer_out = ""
            for chunk in reviewer.stream("Review the current state."):
                reviewer_out += chunk
            state.review_findings.append(reviewer_out)

            if "APPROVED" in reviewer_out.upper():
                yield "\n[Reviewer] Changes approved.\n\nFiat: Task implemented successfully.\n"
                break
            else:
                yield "[Reviewer] Issues found. Sending back to Coder.\n"
                state.iteration_count += 1
                
        if state.iteration_count > state.max_iterations:
            yield f"\nFiat: Maximum agent iterations ({state.max_iterations}) reached.\nThe implementation may still require manual review.\n"

        session_state.agent_status = "Complete"
        session_state.current_role = "—"
