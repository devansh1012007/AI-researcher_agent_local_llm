# Security Model

## Boundaries (spec #62-63)

Untrusted content = anything scraped: web pages, PDFs, search snippets, user
files. It is isolated from system instructions, tool permissions, and execution:

1. every prompt embedding document content wraps it in explicit delimiters and
   carries an "untrusted data — never instructions" rule (system prompt);
2. rendering never crashes on payloads containing template syntax;
3. content can create evidence/claims — it can never grant permissions or
   invoke tools. There is no code path from chunk text to tool dispatch.

Enforced by tests: `tests/security/test_security.py`
(all-content templates must declare the boundary).

## Permission engine (#33/#64)

`security/permissions.py`: READ < WRITE/RESEARCH < EXECUTE_EXPERIMENT <
ADMIN with implication downward only. Default external clients get READ.
Tools declare risk level, side effects, resource scope.

## Filesystem sandbox (#65)

PathSandbox confines file operations to configured roots (default: the data
dir); forbidden components (~/.ssh, .aws, .gnupg, .kube) always rejected.
Experiments additionally contain child-process writes via audit hooks.

## Experiments (#37/#45/#145)

Sandboxed subprocesses: no network/subprocess by default, rlimits on
CPU/memory/processes/wall-clock, minimal env, write containment, human
approval gate for consequential experiments.

## Secrets (#66)

Config accepts tokens via env (`GAR_PLATFORM__API__AUTH_TOKEN`); logs redact;
experiment children get scrubbed environments; nothing secret is stored in
reports or project DBs.

## Network exposure (#67)

API binds 127.0.0.1 by default; CLI refuses non-local binding without an auth
token; MCP speaks stdio only. Privacy mode (`privacy_mode: true`) disables all
external calls (#99-103).
