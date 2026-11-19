import ast
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fiat.execution.models import (
    CommandVerificationResult,
    FileVerificationResult,
    VerificationEvidence,
)


class TaskVerifier:
    @staticmethod
    def verify_task(
        task: Any,
        workspace_root: Path,
        command_runner: Callable[[str], CommandVerificationResult] | None = None,
        verification_commands: list[str] | None = None
    ) -> VerificationEvidence:
        workspace_root = Path(workspace_root).resolve()
        target_files = getattr(task, "target_files", [])
        file_checks = []

        for rel in target_files:
            p = (workspace_root / rel).resolve()
            if not p.is_relative_to(workspace_root):
                file_checks.append(FileVerificationResult(file_path=rel, exists=False, syntax_valid=False, error="Path traversal outside workspace", passed=False))
                continue

            exists = p.exists() and p.is_file()
            syntax_valid = True
            sha_after = None
            err = None

            if exists:
                try:
                    content = p.read_bytes()
                    sha_after = hashlib.sha256(content).hexdigest()
                    if p.suffix.lower() == ".py":
                        ast.parse(content.decode("utf-8", errors="replace"))
                except SyntaxError as se:
                    syntax_valid = False
                    err = str(se)
                except Exception as ex:
                    syntax_valid = False
                    err = str(ex)

            passed = exists and syntax_valid
            file_checks.append(FileVerificationResult(
                file_path=rel,
                exists=exists,
                syntax_valid=syntax_valid,
                sha256_after=sha_after,
                error=err,
                passed=passed
            ))

        command_checks = []
        if verification_commands:
            if command_runner is None:
                return VerificationEvidence(verified=False, file_checks=file_checks, command_checks=[], failure_reason="verification_commands provided without command_runner")
            for cmd in verification_commands:
                res = command_runner(cmd)
                command_checks.append(res)

        if not file_checks and not command_checks:
            return VerificationEvidence(verified=False, failure_reason="No target files or verification commands provided for verification")

        all_files_pass = all(f.passed for f in file_checks)
        all_cmds_pass = all(c.passed for c in command_checks) if command_checks else True
        verified = all_files_pass and all_cmds_pass

        failure_reason = None
        if not verified:
            reasons = [f"File {f.file_path} failed (exists={f.exists}, syntax_valid={f.syntax_valid}, err={f.error})" for f in file_checks if not f.passed]
            reasons += [f"Command '{c.command}' exited with code {c.exit_code}" for c in command_checks if not c.passed]
            failure_reason = "; ".join(reasons)

        return VerificationEvidence(verified=verified, file_checks=file_checks, command_checks=command_checks, failure_reason=failure_reason)
