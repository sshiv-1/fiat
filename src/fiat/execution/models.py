from enum import Enum
from pydantic import BaseModel, Field

class TaskExecutionState(str, Enum):
    QUEUED = "queued"
    BLOCKED_BY_DEPENDENCY = "blocked_by_dependency"
    BLOCKED_UPSTREAM_FAILED = "blocked_upstream_failed"
    AWAITING_PERMISSION = "awaiting_permission"
    RUNNING = "running"
    VERIFYING = "verifying"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERED = "recovered"

class RunLifecycle(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED_PERMISSION = "paused_permission"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERED = "recovered"

class CommandVerificationResult(BaseModel):
    command: str
    exit_code: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    duration_ms: int = 0
    passed: bool

class FileVerificationResult(BaseModel):
    file_path: str
    exists: bool
    syntax_valid: bool = True
    sha256_after: str | None = None
    error: str | None = None
    passed: bool

class VerificationEvidence(BaseModel):
    verified: bool
    file_checks: list[FileVerificationResult] = Field(default_factory=list)
    command_checks: list[CommandVerificationResult] = Field(default_factory=list)
    failure_reason: str | None = None

class TaskAttemptRecord(BaseModel):
    attempt_number: int
    started_at: str
    ended_at: str | None = None
    state: TaskExecutionState
    dirty_files: list[str] = Field(default_factory=list)
    permission_audit_ids: list[str] = Field(default_factory=list)
    verification: VerificationEvidence | None = None
    error_message: str | None = None

class TaskCheckpoint(BaseModel):
    run_id: str
    plan_id: str
    task_id: str
    state: TaskExecutionState
    attempt_count: int = 0
    max_retries: int = 2
    pre_task_file_hashes: dict[str, str | None] = Field(default_factory=dict)
    post_task_file_hashes: dict[str, str | None] = Field(default_factory=dict)
    attempts: list[TaskAttemptRecord] = Field(default_factory=list)
    updated_at: str

class ExecutionSummary(BaseModel):
    total_tasks: int
    completed_tasks: int = 0
    failed_tasks: int = 0
    blocked_tasks: int = 0
    cancelled_tasks: int = 0
    recovered_tasks: int = 0

class ExecutionRun(BaseModel):
    run_id: str
    plan_id: str
    plan_sha256: str
    lifecycle: RunLifecycle
    execution_order: list[str]
    task_states: dict[str, TaskExecutionState]
    created_at: str
    updated_at: str
    summary: ExecutionSummary
