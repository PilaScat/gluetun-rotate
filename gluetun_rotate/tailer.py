from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


class Tailer:
    def __init__(self, path: Path, from_start: bool = False) -> None:
        self.path = path
        self._offset = 0
        self._key: tuple[int, int] | None = None
        self._started = from_start

    def _identity(self) -> tuple[int, int] | None:
        try:
            info = self.path.stat()
        except OSError:
            return None
        return (info.st_dev, info.st_ino)

    def read(self) -> Iterator[str]:
        identity = self._identity()
        if identity is None:
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return

        if not self._started:
            self._started = True
            self._key = identity
            self._offset = size
            return

        if identity != self._key or size < self._offset:
            self._key = identity
            self._offset = 0
        if size <= self._offset:
            return

        try:
            with self.path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read(size - self._offset)
        except OSError:
            return

        complete, separator, _ = chunk.rpartition(b"\n")
        if not separator:
            return
        self._offset += len(complete) + len(separator)
        for raw in complete.split(b"\n"):
            if raw:
                yield raw.decode("utf-8", "replace").rstrip("\r")
