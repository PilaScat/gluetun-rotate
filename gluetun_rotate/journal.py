from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


class Journal:
    def __init__(self, path: Path, limit: int) -> None:
        self.path = path
        self.limit = max(limit, 1)

    def write(self, event: str, **facts: object) -> dict:
        record = {"at": time.time(), "event": event, **facts}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        self._trim()
        return record

    def read(self, limit: int | None = None) -> list[dict]:
        try:
            with self.path.open(encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return []
        records = []
        for line in lines[-(limit or self.limit) :]:
            try:
                loaded = json.loads(line)
            except ValueError:
                continue
            if isinstance(loaded, dict):
                records.append(loaded)
        return records

    def _trim(self) -> None:
        try:
            with self.path.open(encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return
        if len(lines) <= self.limit * 4:
            return
        descriptor, temporary = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.writelines(lines[-self.limit :])
            os.replace(temporary, self.path)
        except OSError:
            Path(temporary).unlink(missing_ok=True)
