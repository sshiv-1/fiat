"""Centralized, fail-closed authorization for Fiat's sensitive operations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from fiat.tools.terminal import CommandRequest
from fiat.tools.workspace import WorkspaceManager


class OperationCategory(StrEnum):
    FILE_MODIFICATION = "FILE_MODIFICATION"
    COMMAND_EXECUTION = "COMMAND_EXECUTION"
    DEPENDENCY_INSTALLATION = "DEPENDENCY_INSTALLATION"
    NETWORK_OPERATION = "NETWORK_OPERATION"
    GIT_OPERATION = "GIT_OPERATION"
    DESTRUCTIVE_OPERATION = "DESTRUCTIVE_OPERATION"
    SYSTEM_OPERATION = "SYSTEM_OPERATION"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PermissionDecision(StrEnum):
    ALLOW_ONCE = "ALLOW_ONCE"
    ALLOW_SESSION = "ALLOW_SESSION"
    ALLOW_WORKSPACE = "ALLOW_WORKSPACE"
    DENY = "DENY"


@dataclass(frozen=True)
class PermissionRequest:
    """The exact operation a user is being asked to authorize."""

    category: OperationCategory
    operation: str
    resource: str
    reason: str
    risk: RiskLevel
    command: tuple[str, ...] = ()
    working_directory: str = ""
    destructive: bool = False
    persistent_grant_allowed: bool = True

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "category": self.category.value,
                "operation": self.operation,
                "resource": self.resource,
                "command": self.command,
                "working_directory": self.working_directory,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def can_persist_workspace_grant(self) -> bool:
        return (
            self.persistent_grant_allowed
            and not self.destructive
            and self.category != OperationCategory.DESTRUCTIVE_OPERATION
        )


@dataclass(frozen=True)
class PermissionGrant:
    fingerprint: str
    category: str
    operation: str
    resource: str
    command: tuple[str, ...]
    working_directory: str
    created_at: str

    @classmethod
    def from_request(cls, request: PermissionRequest) -> PermissionGrant:
        return cls(
            fingerprint=request.fingerprint,
            category=request.category.value,
            operation=request.operation,
            resource=request.resource,
            command=request.command,
            working_directory=request.working_directory,
            created_at=datetime.now(UTC).isoformat(),
        )


PermissionPrompt = Callable[[PermissionRequest], PermissionDecision]


class PermissionStore:
    """Durable exact-match workspace grants and audit events, separate from plans."""

    schema_version = 1

    def __init__(self, workspace: WorkspaceManager) -> None:
        self.directory = workspace.root / ".fiat"
        self.grants_path = self.directory / "permissions.json"
        self.audit_path = self.directory / "permission-audit.json"

    def load_grants(self) -> dict[str, PermissionGrant]:
        if not self.grants_path.is_file():
            return {}
        try:
            payload = json.loads(self.grants_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.schema_version:
                return {}
            grants = [self._validated_grant(item) for item in payload.get("grants", [])]
            return {grant.fingerprint: grant for grant in grants}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _validated_grant(value: object) -> PermissionGrant:
        if not isinstance(value, dict):
            raise ValueError("permission grant must be an object")
        command = value.get("command", [])
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise ValueError("permission grant command is invalid")
        grant = PermissionGrant(
            fingerprint=str(value["fingerprint"]),
            category=str(value["category"]),
            operation=str(value["operation"]),
            resource=str(value["resource"]),
            command=tuple(command),
            working_directory=str(value["working_directory"]),
            created_at=str(value["created_at"]),
        )
        request = PermissionRequest(
            category=OperationCategory(grant.category),
            operation=grant.operation,
            resource=grant.resource,
            reason="stored grant validation",
            risk=RiskLevel.LOW,
            command=grant.command,
            working_directory=grant.working_directory,
        )
        if grant.fingerprint != request.fingerprint:
            raise ValueError("permission grant fingerprint is invalid")
        return grant

    def save_grants(self, grants: dict[str, PermissionGrant]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            self.grants_path,
            {
                "schema_version": self.schema_version,
                "grants": [asdict(grant) for _, grant in sorted(grants.items())],
            },
        )

    def append_audit(self, event: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        events: list[dict[str, object]] = []
        if self.audit_path.is_file():
            try:
                loaded = json.loads(self.audit_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    events = loaded[-999:]
            except (OSError, json.JSONDecodeError):
                events = []
        events.append(event)
        self._atomic_write(self.audit_path, events)

    @staticmethod
    def _atomic_write(path: Path, value: object) -> None:
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(value, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, path)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)


class PermissionManager:
    """Authorizes every sensitive Core operation with exact, fail-closed scope."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        prompt: PermissionPrompt | None = None,
        store: PermissionStore | None = None,
    ) -> None:
        self.workspace = workspace
        self.prompt = prompt
        self.store = store or PermissionStore(workspace)
        self.session_grants: dict[str, PermissionGrant] = {}
        self.workspace_grants = self.store.load_grants()
        self.audit_events: list[dict[str, object]] = []

    def authorize(self, request: PermissionRequest) -> bool:
        """Return whether the exact request is permitted, denying errors by default."""
        try:
            if not request.destructive and request.fingerprint in self.session_grants:
                self._audit(request, "ALLOW_SESSION", "session grant")
                return True
            if (
                request.can_persist_workspace_grant
                and request.fingerprint in self.workspace_grants
            ):
                self._audit(request, "ALLOW_WORKSPACE", "workspace grant")
                return True
            decision = self.prompt(request) if self.prompt else PermissionDecision.DENY
            if not isinstance(decision, PermissionDecision):
                decision = PermissionDecision(str(decision))
            if decision == PermissionDecision.ALLOW_ONCE:
                self._audit(request, decision.value, "one-time grant")
                return True
            if decision == PermissionDecision.ALLOW_SESSION and not request.destructive:
                self.session_grants[request.fingerprint] = PermissionGrant.from_request(request)
                self._audit(request, decision.value, "session grant")
                return True
            if decision == PermissionDecision.ALLOW_WORKSPACE and request.can_persist_workspace_grant:
                grant = PermissionGrant.from_request(request)
                self.workspace_grants[request.fingerprint] = grant
                self.store.save_grants(self.workspace_grants)
                self._audit(request, decision.value, "workspace grant")
                return True
            detail = "persistent grants are forbidden" if decision != PermissionDecision.DENY else "denied"
            self._audit(request, PermissionDecision.DENY.value, detail)
            return False
        except Exception as error:
            self._audit(request, PermissionDecision.DENY.value, f"authorization error: {error}")
            return False

    def authorize_file_modification(
        self, path: str, operation: str, reason: str
    ) -> bool:
        request = PermissionRequest(
            category=OperationCategory.FILE_MODIFICATION,
            operation=operation,
            resource=path,
            reason=reason,
            risk=RiskLevel.HIGH if operation == "overwrite" else RiskLevel.MEDIUM,
            working_directory=str(self.workspace.root),
        )
        return self.authorize(request)

    def authorize_command(self, request: CommandRequest, reason: str) -> bool:
        permission_request = self.classify_command(request, reason)
        return self.authorize(permission_request)

    def classify_command(
        self, request: CommandRequest, reason: str
    ) -> PermissionRequest:
        args = tuple(request.args)
        executable = Path(args[0]).name.casefold()
        command_words = tuple(part.casefold() for part in args)
        category = OperationCategory.COMMAND_EXECUTION
        risk = RiskLevel.MEDIUM
        destructive = False
        operation = "run command"
        persistent_grant_allowed = True
        if executable in {"curl", "curl.exe", "wget", "wget.exe", "git", "git.exe"}:
            if executable.startswith("git"):
                subcommand = command_words[1] if len(command_words) > 1 else ""
                if subcommand in {"reset", "clean"}:
                    category = OperationCategory.DESTRUCTIVE_OPERATION
                    risk = RiskLevel.CRITICAL
                    destructive = True
                    operation = f"git {subcommand}"
                elif subcommand in {"commit", "branch", "checkout", "switch", "rebase", "merge", "push"}:
                    category = OperationCategory.GIT_OPERATION
                    risk = RiskLevel.HIGH
                    operation = f"git {subcommand}"
                    persistent_grant_allowed = subcommand != "push"
                elif subcommand in {"clone", "fetch", "pull"}:
                    category = OperationCategory.NETWORK_OPERATION
                    risk = RiskLevel.HIGH
                    operation = f"git {subcommand}"
                    persistent_grant_allowed = False
            else:
                category = OperationCategory.NETWORK_OPERATION
                risk = RiskLevel.HIGH
                operation = "network request"
        if self._is_dependency_install(command_words):
            category = OperationCategory.DEPENDENCY_INSTALLATION
            risk = RiskLevel.HIGH
            operation = "install dependency"
        if self._looks_destructive(command_words):
            category = OperationCategory.DESTRUCTIVE_OPERATION
            risk = RiskLevel.CRITICAL
            destructive = True
            operation = "destructive command"
        return PermissionRequest(
            category=category,
            operation=operation,
            resource=" ".join(args),
            reason=reason,
            risk=risk,
            command=args,
            working_directory=str(self.workspace.root),
            destructive=destructive,
            persistent_grant_allowed=persistent_grant_allowed,
        )

    @staticmethod
    def _is_dependency_install(args: Sequence[str]) -> bool:
        pairs = set(zip(args, args[1:], strict=False))
        return bool(
            pairs
            & {
                ("pip", "install"),
                ("pip.exe", "install"),
                ("npm", "install"),
                ("npm", "i"),
                ("pnpm", "add"),
                ("yarn", "add"),
                ("uv", "add"),
            }
        )

    @staticmethod
    def _looks_destructive(args: Sequence[str]) -> bool:
        return any(
            word in {"rm", "rmdir", "del", "erase", "remove-item", "format", "reset"}
            for word in args
        )

    def _audit(self, request: PermissionRequest, decision: str, detail: str) -> None:
        event: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "fingerprint": request.fingerprint,
            "category": request.category.value,
            "operation": request.operation,
            "resource": request.resource,
            "command": list(request.command),
            "risk": request.risk.value,
            "decision": decision,
            "detail": detail,
        }
        self.audit_events.append(event)
        try:
            self.store.append_audit(event)
        except Exception:
            pass
