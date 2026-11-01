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

Repository indexing skips common dependency/build directories, binary files,
generated files, symlinks, ignored paths, and protected secrets. Its gitignore
support intentionally covers the common root-level pattern subset rather than
all of Git's nested ignore semantics. JavaScript and TypeScript extraction is a
dependency-free parser approximation; malformed or highly dynamic syntax may
produce partial symbols or imports. Python uses the standard AST and records
syntax failures instead of executing project code.
