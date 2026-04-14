from __future__ import annotations

import json
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

DATE_FORMAT = '%Y-%m-%d'
HOUR_FORMAT = '%H'
PARTITION_FORMAT = DATE_FORMAT + ' ' + HOUR_FORMAT

DEFAULT_RETENTION_HOURS = 24 * 30

TOOL_INPUT_CONTENT_PREVIEW_CHARS = 200
TOOL_INPUT_LARGE_KEYS = frozenset({'content', 'search', 'replace'})


class ObservabilityLogger:
    def __init__(
        self,
        log_dir: Path,
        enabled: bool = True,
        preview_chars: int = 2000,
        retention_hours: int = DEFAULT_RETENTION_HOURS,
    ) -> None:
        self.enabled = enabled
        self.log_dir = log_dir
        self.preview_chars = preview_chars
        self.retention_hours = retention_hours if retention_hours > 0 else DEFAULT_RETENTION_HOURS
        self.events_dir = self.log_dir / 'events'
        self.sessions_dir = self.log_dir / 'sessions'
        self._last_cleanup_hour: Optional[Tuple[int, int, int, int]] = None
        if self.enabled:
            self._ensure_dirs()

    def log_event(self, event_type: str, session_id: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        now = datetime.now(timezone.utc)
        ts = self._format_timestamp(now)
        previewed = self.preview(payload)
        entry = {
            'timestamp': ts,
            'event_type': event_type,
            'session_id': session_id,
            'payload': previewed,
        }
        session_entry = {
            'timestamp': ts,
            'event_type': event_type,
            'payload': previewed,
        }
        try:
            self._ensure_dirs()
            events_line = json.dumps(entry, ensure_ascii=False) + '\n'
            session_line = json.dumps(session_entry, ensure_ascii=False) + '\n'
            events_path, session_path = self._event_paths(session_id, now)
            self._ensure_parent(events_path)
            self._ensure_parent(session_path)
            with events_path.open('a', encoding='utf-8') as handle:
                handle.write(events_line)
            with session_path.open('a', encoding='utf-8') as handle:
                handle.write(session_line)
            self._cleanup_if_needed(now)
        except Exception:
            return

    def log_exception(self, session_id: str, error: Exception, payload: Dict[str, Any], log_dir: Path) -> Optional[Path]:
        now = datetime.now(timezone.utc)
        entry = {
            'timestamp': self._format_timestamp(now),
            'session_id': session_id,
            'error_type': error.__class__.__name__,
            'error_message': str(error),
            'payload': self.preview(payload),
            'traceback': traceback.format_exc(),
        }
        try:
            path = log_dir / now.strftime(DATE_FORMAT) / (uuid.uuid4().hex + '.json')
            self._ensure_parent(path)
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf-8')
            return path
        except Exception:
            return None

    def preview(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) <= self.preview_chars:
                return value
            return value[: self.preview_chars] + f'... [truncated {len(value) - self.preview_chars} chars]'
        if isinstance(value, dict):
            return {str(key): self.preview(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.preview(item) for item in value]
        return value

    def preview_tool_input(self, tool_input: Any) -> Any:
        if not isinstance(tool_input, dict):
            return self.preview(tool_input)
        result = {}
        for key, val in tool_input.items():
            if key in TOOL_INPUT_LARGE_KEYS and isinstance(val, str) and len(val) > TOOL_INPUT_CONTENT_PREVIEW_CHARS:
                result[key] = val[:TOOL_INPUT_CONTENT_PREVIEW_CHARS] + f'... [truncated {len(val) - TOOL_INPUT_CONTENT_PREVIEW_CHARS} chars]'
            else:
                result[key] = self.preview(val)
        return result

    def _format_timestamp(self, moment: datetime) -> str:
        return moment.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _event_paths(self, session_id: str, now: datetime) -> Tuple[Path, Path]:
        date_part = now.strftime(DATE_FORMAT)
        hour_part = now.strftime(HOUR_FORMAT) + '.jsonl'
        return self.events_dir / date_part / hour_part, self.sessions_dir / session_id / date_part / hour_part

    def _ensure_dirs(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.events_dir.mkdir(parents=True, exist_ok=True)
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return

    def _ensure_parent(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def _cleanup_if_needed(self, now: datetime) -> None:
        cleanup_hour = (now.year, now.month, now.day, now.hour)
        if self._last_cleanup_hour == cleanup_hour:
            return
        self._cleanup_expired_logs(now)
        self._last_cleanup_hour = cleanup_hour

    def _cleanup_expired_logs(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=self.retention_hours)
        for root in (self.events_dir, self.sessions_dir):
            self._delete_expired_files(root, cutoff)
            self._prune_empty_dirs(root)

    def _delete_expired_files(self, root: Path, cutoff: datetime) -> None:
        if not root.exists():
            return
        for path in root.rglob('*.jsonl'):
            if self._should_delete_path(path, cutoff):
                try:
                    path.unlink()
                except Exception:
                    continue

    def _should_delete_path(self, path: Path, cutoff: datetime) -> bool:
        partition_time = self._extract_partition_time(path)
        return partition_time is not None and partition_time < cutoff

    def _extract_partition_time(self, path: Path) -> Optional[datetime]:
        try:
            relative = path.relative_to(self.log_dir)
        except ValueError:
            return None
        parts = relative.parts
        if len(parts) == 3 and parts[0] == 'events':
            date_part, hour_part = parts[1], parts[2]
        elif len(parts) == 4 and parts[0] == 'sessions':
            date_part, hour_part = parts[2], parts[3]
        else:
            return None
        if not hour_part.endswith('.jsonl'):
            return None
        try:
            return datetime.strptime(f'{date_part} {hour_part[:-6]}', PARTITION_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _prune_empty_dirs(self, root: Path) -> None:
        if not root.exists():
            return
        for directory in self._walk_dirs_bottom_up(root):
            if directory == root:
                continue
            try:
                next(directory.iterdir())
            except StopIteration:
                try:
                    directory.rmdir()
                except Exception:
                    continue
            except Exception:
                continue

    def _walk_dirs_bottom_up(self, root: Path) -> Iterable[Path]:
        directories = [path for path in root.rglob('*') if path.is_dir()]
        directories.sort(key=lambda item: len(item.parts), reverse=True)
        directories.append(root)
        return directories
