from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class ObservabilityLogger:
    def __init__(self, log_dir: Path, enabled: bool = True, preview_chars: int = 2000) -> None:
        self.enabled = enabled
        self.log_dir = log_dir
        self.preview_chars = preview_chars
        self.events_path = self.log_dir / 'events.jsonl'
        if self.enabled:
            self._ensure_dir()

    def log_event(self, event_type: str, session_id: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': event_type,
            'session_id': session_id,
            'payload': self.preview(payload),
        }
        try:
            self._ensure_dir()
            with self.events_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception:
            return

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

    def _ensure_dir(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
