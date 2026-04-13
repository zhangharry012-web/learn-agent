# Observability Log Rotation Plan

## Overview

This change will operationalize the existing observability logger by replacing the current fixed-file append strategy with date-hour rotation and automatic retention cleanup. The logger will keep the existing JSONL event schema and per-session visibility, but it will write into hour-partitioned files and opportunistically delete files older than the configured retention window.

The implementation will stay concentrated in the observability layer so the current runtime instrumentation in `agent/runtime/agent.py` remains largely unchanged. Configuration will expand in `agent/config.py`, tests will be updated to validate rotated paths and cleanup behavior, and the README will document the new on-disk layout and retention knobs.

## Target file structure

```text
learn-agent/
├── README.md
├── docs/
│   ├── observability-expansion/
│   │   ├── plan.md
│   │   └── research.md
│   └── observability-rotation/
│       ├── plan.md                          # this document
│       └── research.md                     # companion research artifact
├── agent/
│   ├── config.py                           # add rotation/retention config
│   └── runtime/
│       ├── agent.py                        # no structural rewrite; existing calls remain
│       └── observability.py                # hourly path resolution + retention cleanup
└── tests/
    ├── test_agent_runtime.py               # rotated-file and cleanup behavior
    └── test_config.py                      # config defaults and env overrides
```

## Target log layout

The logger will move from flat fixed paths:

```text
logs/observability/events.jsonl
logs/observability/sessions/<session_id>.jsonl
```

To hourly rotated paths:

```text
logs/observability/
├── events/
│   └── 2026-04-13/
│       ├── 10.jsonl
│       └── 11.jsonl
└── sessions/
    └── <session_id>/
        └── 2026-04-13/
            ├── 10.jsonl
            └── 11.jsonl
```

Path rules:

- global event stream rotates by UTC date and hour
- each session gets its own directory under `sessions/<session_id>/`
- session logs rotate on the same date-hour boundary as the global stream
- one JSON object remains one line; only the file partitioning changes

This structure keeps manual inspection simple while avoiding unbounded growth of a single file.

## Architecture diagram

```text
runtime.Agent
   |
   | log_event(event_type, session_id, payload)
   v
ObservabilityLogger
   |
   +--> current UTC timestamp
   |
   +--> resolve global hourly file path
   |       logs/observability/events/YYYY-MM-DD/HH.jsonl
   |
   +--> resolve session hourly file path
   |       logs/observability/sessions/<session_id>/YYYY-MM-DD/HH.jsonl
   |
   +--> ensure parent directories exist
   |
   +--> append serialized JSONL entry to both files
   |
   +--> occasionally / opportunistically cleanup expired files
           based on retention_hours cutoff
```

## Module design

### `agent/runtime/observability.py`

This remains the primary implementation target.

Responsibilities after the change:

- keep the existing event serialization and preview truncation behavior
- derive the write target from the current UTC timestamp
- write each event to both the global hourly file and the session hourly file
- remove expired rotated files based on a configurable retention duration
- keep all cleanup/write failures non-fatal to the runtime

Recommended interface evolution:

```python
class ObservabilityLogger:
    def __init__(
        self,
        log_dir: Path,
        enabled: bool = True,
        preview_chars: int = 2000,
        retention_hours: int = 24 * 30,
    ) -> None: ...

    def log_event(self, event_type: str, session_id: str, payload: dict[str, Any]) -> None: ...
    def preview(self, value: Any) -> Any: ...
```

Recommended internal helpers:

```python
def _event_paths(self, session_id: str, now: datetime) -> tuple[Path, Path]: ...
def _ensure_parent(self, path: Path) -> None: ...
def _cleanup_expired_logs(self, now: datetime) -> None: ...
def _should_delete_path(self, path: Path, cutoff: datetime) -> bool: ...
```

Operational behavior:

1. `log_event(...)` captures `now` once.
2. The logger computes the global and session file paths from `now`.
3. The logger ensures both parent directories exist.
4. The logger appends the same serialized line to both files.
5. The logger triggers a lightweight cleanup pass.

### Rotation strategy

Chosen strategy: directory by date + file by hour.

Rationale:

- file names stay short and grep-friendly
- date partitioning makes bulk inspection and manual deletion intuitive
- per-hour rotation prevents a single file from growing indefinitely
- implementation remains simple with only standard library path handling

Formatting rules:

- date directory: `YYYY-MM-DD`
- hour file: `HH.jsonl` using zero-padded 24-hour UTC hour

### Retention cleanup strategy

Chosen strategy: retention driven by file modification time or parsed timestamp-aligned path age, executed opportunistically from the logger.

Preferred implementation approach:

- compute `cutoff = now - timedelta(hours=retention_hours)`
- walk the `events/` and `sessions/` subtrees
- delete `.jsonl` files whose timestamped partition is older than cutoff
- after file deletion, prune empty directories bottom-up where practical

Why this approach fits:

- avoids additional daemons or scheduled jobs
- works in local CLI use where the process may be short-lived
- leverages the fact that path timestamps are deterministic from the rotation scheme
- keeps cleanup local to the observability subsystem instead of leaking logic into runtime orchestration

Important cleanup guardrails:

- only delete within the configured observability log directory
- ignore non-JSONL files
- swallow cleanup exceptions to preserve runtime reliability
- retention of `<= 0` should be normalized to a safe minimum or fallback default rather than disable cleanup implicitly

### Cleanup cadence

The cleanup should be lightweight and not scan excessively on every append if avoidable.

Recommended implementation:

- track the last cleanup hour in memory
- run cleanup at most once per process per hour boundary
- still perform a cleanup early in a new process so short-lived CLI sessions can eventually prune old files

This balances operational correctness with low overhead.

### `agent/config.py`

Add explicit configuration for retention and, if useful, keep rotation always enabled as the only behavior.

Recommended new fields:

- `observability_retention_hours: int = 24 * 30`

Recommended env key:

- `OBSERVABILITY_RETENTION_HOURS`

Why only retention config is needed:

- the user explicitly requires hourly rotation, so rotation does not need a mode switch yet
- retaining a single simple knob reduces complexity and test surface

Validation expectations:

- invalid env values fall back to the default
- default equals 720 hours (30 days)

### `agent/runtime/agent.py`

The runtime should remain intentionally stable.

Expected change scope:

- update `ObservabilityLogger(...)` construction to pass `retention_hours` from config
- no event-type changes are required for this phase
- existing instrumentation call sites should remain as-is

This preserves the boundary that the runtime emits events and the logger owns storage policy.

### `README.md`

Update the docs to describe:

- the rotated directory layout
- that logs rotate hourly using UTC timestamps
- default retention is 30 days
- retention can be changed with `OBSERVABILITY_RETENTION_HOURS`
- example inspection commands for the new layout

## Detailed data flow

```text
event emitted by runtime
   -> logger builds entry with timestamp/event_type/session_id/payload
   -> logger previews payload to bound line size
   -> logger resolves:
        global path  = events/YYYY-MM-DD/HH.jsonl
        session path = sessions/<session_id>/YYYY-MM-DD/HH.jsonl
   -> logger appends serialized line to both files
   -> logger conditionally runs cleanup if current process has not cleaned this hour
   -> cleanup removes expired *.jsonl files older than cutoff
   -> cleanup prunes empty date/session directories when possible
```

## Design decisions and trade-offs

### 1. Keep rotation logic inside `ObservabilityLogger`

Decision:

- implement all path rotation and cleanup inside `agent/runtime/observability.py`

Alternatives considered:

- make runtime compute paths and pass them down
- introduce a separate maintenance service or CLI command

Why this choice wins:

- storage policy belongs with the logger, not the runtime orchestration layer
- minimizes change surface across the rest of the codebase
- simpler tests because behavior is concentrated in one module

### 2. Use UTC hour partitions

Decision:

- rotate by UTC date-hour, not local timezone

Alternatives considered:

- local timezone-based partitions
- one flat filename with timestamp suffixes

Why this choice wins:

- existing timestamps are already UTC ISO strings
- avoids ambiguity across environments and daylight-saving changes
- keeps naming aligned with emitted event timestamps

### 3. Preserve both global and per-session streams

Decision:

- continue writing each event twice: one global stream and one per-session stream

Alternative considered:

- only keep the global stream and filter by `session_id`

Why this choice wins:

- session-focused inspection remains easy for humans
- current observability behavior already promises per-session logs
- no migration of event semantics is required

### 4. Opportunistic cleanup instead of background scheduling

Decision:

- cleanup runs from normal logger activity, bounded to once per process-hour

Alternatives considered:

- add a separate scheduler
- only cleanup on startup
- cleanup on every event write

Why this choice wins:

- no extra process management
- more reliable than startup-only cleanup in long-running sessions
- lower overhead than scanning on every event

### 5. Retention as hours, not days

Decision:

- expose retention in hours

Alternatives considered:

- retention in days
- retention as a free-form duration string

Why this choice wins:

- directly matches the hourly rotation granularity
- easy to parse and test with the standard library
- enables short retention windows in tests without special-case helpers

## Testing strategy

### `tests/test_agent_runtime.py`

Add coverage for:

1. hourly global path creation
   - emit events and assert files exist under `events/YYYY-MM-DD/HH.jsonl`

2. hourly session path creation
   - assert files exist under `sessions/<session_id>/YYYY-MM-DD/HH.jsonl`

3. session/global event parity still holds
   - same event count for the current session stream and the filtered global stream for that session

4. retention cleanup removes expired rotated files
   - pre-create old rotated files older than cutoff
   - emit a new event
   - assert expired files are deleted while current-hour files remain

5. empty directory pruning
   - after old file cleanup, assert stale empty date or session directories are removed where applicable

Recommended test technique:

- instantiate `ObservabilityLogger` directly in a temp workspace
- create old files with path names corresponding to stale hours
- adjust file mtimes if the implementation uses filesystem timestamps as a safety check

### `tests/test_config.py`

Add coverage for:

- default `observability_retention_hours == 720`
- env override via `OBSERVABILITY_RETENTION_HOURS`
- invalid override falls back to default

## Usage and configuration

### Default behavior

Without any new configuration:

- observability remains enabled by default
- logs rotate hourly
- logs older than 30 days are removed automatically

### Environment variables

```text
OBSERVABILITY_ENABLED=true
OBSERVABILITY_LOG_DIR=logs/observability
OBSERVABILITY_PREVIEW_CHARS=2000
OBSERVABILITY_RETENTION_HOURS=720
```

### Example inspection commands

```bash
find logs/observability/events -type f | sort
find logs/observability/sessions -type f | sort
cat logs/observability/events/2026-04-13/11.jsonl
grep '"event_type": "llm_call_completed"' logs/observability/events/2026-04-13/11.jsonl
```

## What stays unchanged

The following should remain unchanged in this phase:

- event payload schema and event type names
- runtime approval flow behavior
- token usage extraction in provider clients
- preview truncation behavior
- tool registry and tool implementations
- CLI interaction model

## Extensibility

This design leaves room for later operational enhancements without another broad refactor:

- size-based rotation in addition to time-based rotation
- compressed archival of older hourly files
- a small log summary/viewer CLI
- configurable cleanup cadence
- optional JSON schema version field in each event

## TODO list

- [ ] Create `docs/observability-rotation/research.md` if this round needs a dedicated artifact alongside the plan
- [ ] Add `observability_retention_hours` config with env parsing and defaults in `agent/config.py`
- [ ] Refactor `ObservabilityLogger` to resolve hourly global and session log paths
- [ ] Add bounded cleanup cadence state to the logger
- [ ] Implement expired rotated file cleanup and empty-directory pruning
- [ ] Wire the new retention config into `Agent` logger construction
- [ ] Update runtime tests to assert hourly path layout and cleanup behavior
- [ ] Update config tests for new defaults and env overrides
- [ ] Update `README.md` to document hourly rotation, retention, and new path examples
- [ ] Run targeted test suites
- [ ] Run the full test suite
- [ ] Commit and push the completed plan round
