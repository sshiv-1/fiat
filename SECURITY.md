# Fiat security limitations

Fiat now resolves file-tool paths beneath an explicit workspace root, rejects
path traversal and symlink escapes, protects common credential files, and uses
atomic writes for file edits. This is a guardrail, not an operating-system
sandbox: Fiat can still change any non-protected file the current user can
write inside the selected workspace.

Terminal execution does not use a shell, blocks shell operators in legacy
string commands, removes common secret-bearing environment variables, runs in
the workspace, limits output, and asks for approval unless a command is
explicitly classified read-only. An approved executable or script can still
perform arbitrary actions permitted to the current user; approval is not a
sandbox and users should inspect commands before approving them.

## Phase 2 authorization boundaries

Fiat routes its Core-exposed file modifications and non-read-only terminal
commands through a centralized permission manager. The manager asks for the
exact target or command, working directory, reason, category, and risk level.
It can grant one operation once, remember the exact operation for an in-memory
session, or persist an exact non-destructive workspace grant. Permission
matching includes command arguments and target resource, so a grant for one
operation cannot authorize another.

Destructive operations never receive persistent grants. Prompt interruption,
malformed saved permissions, and authorization failures deny sensitive work.
Workspace grants and audit records are stored separately from plan data under
the workspace-local `.fiat/` directory. Permission decisions never bypass
path containment, protected-file checks, shell-free command parsing, or the
terminal executor's existing limits.

Plan Mode only exposes read-only repository tools. It persists Fiat's own
validated plan metadata but does not write user source files, execute commands,
or perform an approved plan. Phase 3 will need a separately reviewed executor
that consumes approved plan revisions.

Repository indexing skips common dependency/build directories, binary files,
generated files, symlinks, ignored paths, and protected secrets. Its gitignore
support intentionally covers the common root-level pattern subset rather than
all of Git's nested ignore semantics. JavaScript and TypeScript extraction is a
dependency-free parser approximation; malformed or highly dynamic syntax may
produce partial symbols or imports. Python uses the standard AST and records
syntax failures instead of executing project code.
