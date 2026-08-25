# Experiments

From design to knowledge update (spec #34/#164):

```
design → register → HUMAN APPROVAL → execute (sandbox) → capture
       → verdict vs pre-registered criteria → evidence → hypothesis update
```

## Registry

Experiments are Phase 3 entities (`Experiment`, `experiment_results`) bound to
a hypothesis + methodology. Registration via services/MCP marks the experiment
`READY_FOR_HUMAN_APPROVAL`. Execution of an unapproved experiment returns
BLOCKED — the gate is enforced at the runner, not the UI (#45).

## Sandbox (spec #37/#145)

`experiments/runner.py` executes each experiment as `python -I -c` with:

- **audit-hook guard**: network (socket.connect/getaddrinfo/bind) and process
  spawning (subprocess.Popen) denied by default; file WRITES outside the
  experiment workdir raise PermissionError. Imports/reads stay free so normal
  code runs.
- **rlimits**: RLIMIT_AS (memory_mb), RLIMIT_CPU (cpu_seconds), NPROC cap;
  wall-clock timeout with hard kill.
- **environment**: minimal env — no keys/tokens/secrets leak into children.
- **filesystem**: cwd pinned under `<data_dir>/<project>/experiments/<id>/`,
  validated through PathSandbox.

## Configuration & reproducibility (#38/#39)

```json
{"code": "...", "entrypoint": "path.py", "seed": 42,
 "configuration": {"model": "baseline"},
 "timeout_seconds": 1800, "memory_mb": 4096, "cpu_seconds": 1800,
 "network_enabled": false}
```

Every run persists `manifest.json`: code hash, config hash, seed, python
version, platform, limits, timestamps. Identical code+config ⇒ identical
manifest hashes; comparison tooling uses this to decide comparability.

## Results & artifacts (#40/#42)

stdout/stderr/exit code stored verbatim (`stdout.txt`, `stderr.txt`) — LLM
interpretation never overwrites raw output. Metrics read from the child's
`metrics.json`; any other files become artifacts listed in the result row.

## Comparison (#41)

`compare_experiments()` answers: same methodology? same environment? how many
config variables differ? Verdicts: COMPARABLE, NOT_COMPARABLE_METHODOLOGY,
MULTIPLE_VARIABLES_CHANGED, ENVIRONMENT_MISMATCH — plus per-metric deltas only
when comparable.

## Result → knowledge (#43/#44)

Ingestion classifies the outcome against the methodology's PRE-REGISTERED
success/failure/inconclusive conditions, stores a first-class
EXPERIMENT_RESULT-provenance evidence item (tier 1), and walks the hypothesis
through its legal lifecycle transitions with explicit confidence deltas.
