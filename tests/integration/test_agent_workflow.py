import json

from fiat.agents.orchestrator import Orchestrator
from fiat.agents.protocol import WorkflowStatus
from fiat.tools.workspace import WorkspaceManager


class Provider:
    def __init__(self, payload):
        self.payload = payload

    def stream(self, _prompt):
        yield self.payload


class Core:
    def __init__(self, root):
        self.workspace = WorkspaceManager(root)
        self.read_file = lambda *_: ""
        self.list_files = lambda *_: ""
        self.glob_files = lambda *_: ""
        self.grep_search = lambda *_: ""
        self.edit_file = lambda *_: ""
        self.multi_edit = lambda *_: ""
        self.run_command = lambda *_: "Exit code 0"


def test_verified_workflow_completes_without_external_llm_calls(tmp_path, monkeypatch):
    payloads = iter(
        [
            '{"workflow":"COMPLEX"}',
            json.dumps({"status": "PASS", "summary": "plan", "plan": ["edit"]}),
            json.dumps(
                {
                    "status": "PASS",
                    "summary": "implemented",
                    "files_changed": ["module.py"],
                }
            ),
            json.dumps(
                {"status": "PASS", "summary": "tests passed", "commands": ["pytest"]}
            ),
            json.dumps({"status": "PASS", "summary": "reviewed", "findings": []}),
        ]
    )
    orchestrator = Orchestrator(Core(tmp_path))
    monkeypatch.setattr(orchestrator, "_create_agent", lambda *_: Provider(next(payloads)))

    output = "".join(orchestrator.run("Make a change"))

    assert "verified successfully" in output
    assert orchestrator.last_state.status == WorkflowStatus.PASS
    assert orchestrator.last_state.files_modified == ["module.py"]
