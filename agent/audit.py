"""Append-only JSON Lines audit log: one line per event, one file per run."""

import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **fields) -> None:
        record = {"at": datetime.now(timezone.utc).isoformat(), "event": kind, **fields}
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")
