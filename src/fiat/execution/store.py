import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Callable, Any
from fiat.planning.models import PlanLifecycle
from fiat.planning.validation import PlanValidator
from fiat.execution.models import ExecutionRun, TaskCheckpoint, ExecutionSummary, RunLifecycle, TaskExecutionState

class ExecutionStore:
    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.runs_dir = self.workspace_root / ".fiat" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def compute_plan_sha256(self, plan_path_or_bytes: Path | bytes) -> str:
        if isinstance(plan_path_or_bytes, Path):
            data = plan_path_or_bytes.read_bytes()
        else:
            data = plan_path_or_bytes
        return hashlib.sha256(data).hexdigest()

    def recompute_summary(self, task_states: dict[str, TaskExecutionState]) -> ExecutionSummary:
        total = len(task_states)
        completed = sum(1 for s in task_states.values() if s == TaskExecutionState.COMPLETED)
        failed = sum(1 for s in task_states.values() if s == TaskExecutionState.FAILED)
        blocked = sum(1 for s in task_states.values() if s in {TaskExecutionState.BLOCKED_BY_DEPENDENCY, TaskExecutionState.BLOCKED_UPSTREAM_FAILED})
        cancelled = sum(1 for s in task_states.values() if s == TaskExecutionState.CANCELLED)
        recovered = sum(1 for s in task_states.values() if s == TaskExecutionState.RECOVERED)
        return ExecutionSummary(
            total_tasks=total,
            completed_tasks=completed,
            failed_tasks=failed,
            blocked_tasks=blocked,
            cancelled_tasks=cancelled,
            recovered_tasks=recovered
        )

    def create_run(self, plan: Any, plan_raw_bytes: bytes, execution_order: list[str] | None = None, run_id: str | None = None) -> ExecutionRun:
        # Check plan lifecycle — Plan uses .status, some callers may use .lifecycle
        lifecycle = getattr(plan, "status", None) or getattr(plan, "lifecycle", None)
        if lifecycle != PlanLifecycle.APPROVED:
            raise ValueError("Only APPROVED plans can be executed")

        run_id = run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        plan_id = getattr(plan, "plan_id", None) or getattr(plan, "id", "default_plan")
        plan_sha256 = self.compute_plan_sha256(plan_raw_bytes)

        if execution_order is None:
            # topological_order returns list[PlanTask]; extract task_ids
            ordered_tasks = PlanValidator.topological_order(plan)
            execution_order = [t.task_id for t in ordered_tasks]

        tasks = getattr(plan, "tasks", [])
        # PlanTask uses .task_id; fall back to .id for duck-typed objects
        task_map = {(t.task_id if hasattr(t, "task_id") else t.id): t for t in tasks}

        task_states = {}
        for tid in execution_order:
            t_obj = task_map.get(tid)
            deps = getattr(t_obj, "dependencies", []) if t_obj else []
            if not deps:
                task_states[tid] = TaskExecutionState.QUEUED
            else:
                task_states[tid] = TaskExecutionState.BLOCKED_BY_DEPENDENCY

        now = datetime.utcnow().isoformat()
        summary = self.recompute_summary(task_states)

        run = ExecutionRun(
            run_id=run_id,
            plan_id=str(plan_id),
            plan_sha256=plan_sha256,
            lifecycle=RunLifecycle.CREATED,
            execution_order=execution_order,
            task_states=task_states,
            created_at=now,
            updated_at=now,
            summary=summary
        )

        run_dir = self.runs_dir / run_id
        checkpoints_dir = run_dir / "checkpoints"
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        self.save_run(run)

        for tid in execution_order:
            ckpt = TaskCheckpoint(
                run_id=run_id,
                plan_id=str(plan_id),
                task_id=tid,
                state=task_states[tid],
                updated_at=now
            )
            self.save_checkpoint(ckpt)

        return run

    def save_run(self, run: ExecutionRun) -> None:
        run_dir = self.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "run.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load_run(self, run_id: str) -> ExecutionRun:
        path = self.runs_dir / run_id / "run.json"
        return ExecutionRun.model_validate_json(path.read_text(encoding="utf-8"))

    def save_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        ckpt_dir = self.runs_dir / checkpoint.run_id / "checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        path = ckpt_dir / f"{checkpoint.task_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load_checkpoint(self, run_id: str, task_id: str) -> TaskCheckpoint:
        path = self.runs_dir / run_id / "checkpoints" / f"{task_id}.json"
        return TaskCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))

    def snapshot_target_files(self, run_id: str, task_id: str, target_files: list[str]) -> dict[str, str | None]:
        hashes = {}
        backup_dir = self.runs_dir / run_id / "backups" / task_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        for rel in target_files:
            p = (self.workspace_root / rel).resolve()
            if not p.is_relative_to(self.workspace_root):
                raise ValueError(f"Path traversal detected: {rel}")
            
            if p.exists() and p.is_file():
                content = p.read_bytes()
                h = hashlib.sha256(content).hexdigest()
                hashes[rel] = h
                dest = backup_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            else:
                hashes[rel] = None

        ckpt = self.load_checkpoint(run_id, task_id)
        ckpt.pre_task_file_hashes = hashes
        ckpt.updated_at = datetime.utcnow().isoformat()
        self.save_checkpoint(ckpt)
        return hashes

    def restore_target_files(self, run_id: str, task_id: str) -> list[str]:
        ckpt = self.load_checkpoint(run_id, task_id)
        restored = []
        backup_dir = self.runs_dir / run_id / "backups" / task_id

        for rel, sha_before in ckpt.pre_task_file_hashes.items():
            target_p = (self.workspace_root / rel).resolve()
            if sha_before is None:
                if target_p.exists():
                    target_p.unlink()
                    restored.append(rel)
            else:
                src = backup_dir / rel
                if src.exists():
                    target_p.parent.mkdir(parents=True, exist_ok=True)
                    target_p.write_bytes(src.read_bytes())
                    restored.append(rel)
        return restored

    def acquire_lock(self, run_id: str, plan_id: str) -> None:
        lock_path = self.runs_dir / "active.lock"
        if lock_path.exists():
            try:
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                if data.get("run_id") != run_id:
                    raise RuntimeError(f"Active execution lock held by run {data.get('run_id')}")
            except Exception as e:
                if isinstance(e, RuntimeError):
                    raise e
        lock_data = {"run_id": run_id, "plan_id": plan_id, "pid": os.getpid(), "acquired_at": datetime.utcnow().isoformat()}
        lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    def release_lock(self, run_id: str) -> None:
        lock_path = self.runs_dir / "active.lock"
        if lock_path.exists():
            try:
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                if data.get("run_id") == run_id:
                    lock_path.unlink()
            except Exception:
                pass
