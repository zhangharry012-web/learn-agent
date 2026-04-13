# Observability Log Rotation Research

## Scope

This research covers the first operational hardening round for the existing observability subsystem in `learn-agent`, focused on two concrete requirements:

- rotate observability logs by date and hour
- automatically clean up historical logs older than the retention window, with the retention duration configurable and defaulting to one month

The goal is to extend the current logging implementation without rewriting the runtime event model, the existing instrumentation call sites, or the provider usage normalization that was added in the previous round.

## Current implementation baseline

### Logger responsibilities today

`agent/runtime/observability.py` currently owns the full storage behavior for observability events.

The current `ObservabilityLogger` constructor shape is:

```python
class ObservabilityLogger:
    def __init__(self, log_dir: Path, enabled: bool = True, preview_chars: int = 2000) -> None:
        self.enabled = enabled
        self.log_dir = log_dir
        self.preview_chars = preview_chars
        self.events_path = self.log_dir / 'events.jsonl'
        self.sessions_dir = self.log_dir / 'sessions'
        if self.enabled:
            self._ensure_dirs()
```

Important facts:

- log storage policy is fully encapsulated here already
- the module uses only standard library components
- the logger is intentionally failure-tolerant and never raises into the runtime
- the logger already writes both a global stream and a per-session stream
- payload preview/truncation is already centralized here

This means hourly rotation and retention cleanup can be introduced by evolving this one module instead of spreading path logic through the runtime.

### Write path behavior today

Current write behavior is fixed-path append:

```python
with self.events_path.open('a', encoding='utf-8') as handle:
    handle.write(serialized)
with (self.sessions_dir / f'{session_id}.jsonl').open('a', encoding='utf-8') as handle:
    handle.write(serialized)
```

Implications:

- the global file grows indefinitely as `events.jsonl`
- each session file grows indefinitely as `sessions/<session_id>.jsonl`
- there is no partitioning by time
- there is no cleanup of old logs
- manual inspection becomes progressively harder as files grow larger

This is the exact storage behavior that must change.

## Runtime integration surface

### `agent/runtime/agent.py`

The runtime already uses the logger as a collaborator and passes every event through `self.observability.log_event(...)`.

Important current initialization pattern:

```python
self.observability = observability_logger or ObservabilityLogger(
    log_dir=self.workspace_root / self.config.observability_log_dir,
    enabled=self.config.observability_enabled,
    preview_chars=self.config.observability_preview_chars,
)
```

Important consequence:

- the runtime currently knows only about the logger constructor arguments
- event call sites do not depend on log file layout
- rotation and cleanup can remain invisible to most of `Agent`
- only constructor wiring likely needs to change once retention config is added

This is a strong sign that the storage policy should remain entirely inside `ObservabilityLogger`.

## Existing configuration surface

### `agent/config.py`

Current observability-related config is minimal:

```python
observability_enabled: bool = field(default_factory=lambda: _get_env_bool('OBSERVABILITY_ENABLED', True))
observability_log_dir: str = field(
    default_factory=lambda: _get_env_value('OBSERVABILITY_LOG_DIR', 'logs/observability')
)
observability_preview_chars: int = field(
    default_factory=lambda: _get_env_int('OBSERVABILITY_PREVIEW_CHARS', 2000)
)
```

What this means:

- the system already has a stable env-driven config pattern
- adding retention config is straightforward and consistent with current design
- there is no existing rotation or retention toggle to preserve

The missing piece is a retention-duration field. The user requirement specifically says one month by default and configurable duration, so the natural extension is an integer retention setting.

## Existing documentation surface

### `README.md`

The README still documents the old fixed layout:

```text
logs/observability/events.jsonl
logs/observability/sessions/<session_id>.jsonl
```

And the roadmap still says:

- Add log rotation if observability volume grows further

Important implication:

- the README is now stale relative to the requested enhancement
- once implemented, the roadmap item should be reduced or removed because this specific capability will no longer be future work
- example inspection commands must be updated because `tail` against one fixed file is no longer the whole story

## Existing test coverage

### `tests/test_agent_runtime.py`

Current runtime tests assert:

- the global events file exists
- the per-session file exists
- event counts match
- key event types are emitted
- token usage is present
- shell fallback is logged
- approval denial is logged

But they do not validate:

- time-partitioned global paths
- time-partitioned session paths
- cleanup of stale files
- pruning of stale directories
- retention configuration wiring

So the current tests validate event semantics, not storage lifecycle.

### `tests/test_config.py`

Current config tests validate:

- default observability flags and path values
- env-file overrides for existing observability fields

They do not validate:

- a new retention field default
- invalid retention fallback behavior
- env override for retention duration

So config coverage must grow with the new setting.

## Best-fit storage design for hourly rotation

### Why rotation belongs in the logger

The runtime layer emits semantic events. The logger owns physical persistence. The current design already respects that boundary.

If rotation were implemented outside the logger, the codebase would likely suffer from:

- duplicate timestamp/path logic
- more complex runtime instrumentation code
- harder testing because storage policy would be smeared across layers

The best-fit design is therefore:

- keep event call sites unchanged
- make `ObservabilityLogger` compute write targets dynamically from the current time

### Global hourly partitioning

A practical global layout is:

```text
logs/observability/events/YYYY-MM-DD/HH.jsonl
```

Advantages:

- natural grouping by day
- hour-level bounded file size
- simple human browsing with `find` and `sort`
- predictable path derivation from timestamps

This is more operator-friendly than a flat directory with filenames like `events-2026-04-13-11.jsonl`, especially once many hours accumulate.

### Per-session hourly partitioning

A practical session layout is:

```text
logs/observability/sessions/<session_id>/YYYY-MM-DD/HH.jsonl
```

Advantages:

- preserves the current “one session has its own path” mental model
- allows long sessions that cross hour boundaries to remain inspectable by time slice
- avoids mixing multiple sessions into a single per-hour file under `sessions/`

This design also keeps session inspection intuitive: start with `sessions/<session_id>/`, then browse by day and hour.

## Retention cleanup design options

The cleanup requirement is:

- automatically remove historical logs older than one month by default
- allow the retention duration to be configured

There are several implementation options.

### Option A: Cleanup on every write

Approach:

- every `log_event(...)` walks the entire observability tree and removes expired files

Pros:

- simplest correctness model
- cleanup always runs whenever logs are written

Cons:

- unnecessary repeated directory scans
- overhead grows with log volume
- less elegant operationally

This is workable for a tiny codebase, but it is avoidably noisy.

### Option B: Cleanup once per process startup only

Approach:

- cleanup runs in `__init__`
- later writes only append

Pros:

- very low steady-state overhead
- simple mental model

Cons:

- long-running sessions may never cleanup while running
- cleanup frequency depends entirely on process lifecycle

This is acceptable in a short-lived CLI, but weaker if the runtime later becomes longer-lived.

### Option C: Opportunistic cleanup with in-process cadence control

Approach:

- cleanup is triggered from normal logging activity
- the logger remembers the last cleanup hour and only rescans once per process-hour

Pros:

- automatic without a background scheduler
- avoids scanning on every event
- works for both short-lived and longer-lived sessions
- remains self-contained in the logger

Cons:

- slightly more state in the logger
- a little more implementation complexity than the first two options

This is the best fit for the current architecture and likely the strongest operational trade-off.

## How to determine expiration

Two main ways exist.

### Path-derived partition age

Approach:

- parse `YYYY-MM-DD/HH.jsonl`
- reconstruct the partition datetime in UTC
- delete if the partition is older than the cutoff

Pros:

- matches the intended semantics exactly
- independent of filesystem mtime drift
- deterministic and easy to reason about

Cons:

- requires careful parsing logic for both event and session paths
- must ignore malformed paths safely

### Filesystem modification time

Approach:

- inspect `stat().st_mtime`
- compare with cutoff

Pros:

- implementation is simple
- independent of directory naming conventions

Cons:

- mtime may shift if a file is touched for any reason
- less semantically aligned than partition timestamps
- tests may need explicit mtime manipulation

Best practical choice for this project:

- use path-derived age as the primary rule because the rotation scheme is deterministic
- optionally tolerate malformed paths by skipping them rather than falling back to aggressive deletion

This gives a safer cleanup policy.

## Directory pruning requirements

Once old hourly files are deleted, empty directories may remain such as:

- `logs/observability/events/2026-03-01/`
- `logs/observability/sessions/<session_id>/2026-03-01/`
- possibly a now-empty `logs/observability/sessions/<session_id>/`

If these are never pruned, the filesystem gradually accumulates dead structure even though log files are gone.

So cleanup should include bottom-up pruning of empty directories under:

- `events/`
- `sessions/`

Pruning must remain conservative:

- only remove directories inside the observability tree
- never remove the observability root itself unnecessarily
- ignore errors silently

## Config shape recommendation

The cleanest config extension is:

```python
observability_retention_hours: int = field(
    default_factory=lambda: _get_env_int('OBSERVABILITY_RETENTION_HOURS', 24 * 30)
)
```

Why hours are a good unit:

- rotation is hourly, so retention aligns naturally
- tests can use very short windows without day-based awkwardness
- parsing stays consistent with current integer config helpers

One month default becomes `720` hours.

Potential edge cases:

- invalid env values should fall back to default through `_get_env_int`
- zero or negative values should not create unsafe deletion semantics

The logger should normalize such values to a safe minimum or fallback default.

## Backward-compatibility considerations

This change alters only the physical log layout, not the event payload schema.

What remains compatible:

- event objects still contain `timestamp`, `event_type`, `session_id`, `payload`
- runtime instrumentation call sites remain valid
- token usage logging remains unchanged
- preview behavior remains unchanged

What changes operationally:

- scripts or humans reading `logs/observability/events.jsonl` directly will need to update to the new hierarchy
- README examples must be updated accordingly
- tests asserting fixed file paths must be rewritten

Because this is still a local developer-oriented system, this is an acceptable compatibility change.

## Risks and mitigations

### Risk 1: Cleanup accidentally deletes wrong files

Mitigation:

- only walk inside `log_dir / 'events'` and `log_dir / 'sessions'`
- only delete `.jsonl` files whose path format matches expected rotated layout
- skip malformed paths rather than guessing

### Risk 2: Cleanup overhead becomes noticeable

Mitigation:

- rate-limit cleanup to once per process-hour
- keep the directory walk scoped to the observability subtree only

### Risk 3: Rotation logic becomes hard to test

Mitigation:

- factor path derivation and cleanup checks into small helpers
- keep `datetime.now(timezone.utc)` capture centralized so tests can target deterministic helper behavior where possible

### Risk 4: Empty directories accumulate

Mitigation:

- add explicit bottom-up empty-directory pruning in cleanup
- cover it in runtime/logger tests

## Recommended implementation direction

The best implementation direction is:

1. add retention config in `agent/config.py`
2. extend `ObservabilityLogger` with `retention_hours`
3. replace fixed paths with helper-based date-hour path resolution
4. add opportunistic cleanup with once-per-process-hour cadence
5. remove expired `.jsonl` files based on parsed partition timestamps
6. prune empty directories
7. update README and tests to reflect the new layout

This path keeps the change tightly scoped, operationally useful, and aligned with the current architecture.
