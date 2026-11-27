"""The interaction log: one JSON object per line in data/logs/events.jsonl.

It is the raw material for the effort evaluation (Phase 5): time and clicks per
object, manual versus assisted. So it is append-only and never rewritten. Every
event carries the browser's own timestamp (`t`, milliseconds, used for durations)
and the server's receive time (`ts`, seconds), plus the labelling session, the
mode (manual / assisted) and the image.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_lock = threading.Lock()


class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, events: list[dict]) -> int:
        now = round(time.time(), 3)
        lines = [json.dumps({"ts": now, **e}, separators=(",", ":")) for e in events]
        with _lock, self.path.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        return len(lines)

    def server_event(self, kind: str, **data) -> None:
        """Events the server itself originates, e.g. an image upload."""
        self.write([{"event": kind, "origin": "server", **data}])
