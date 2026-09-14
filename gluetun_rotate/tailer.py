from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

HEAD_BYTES = 256


class Tailer:
    def __init__(self, path: Path, from_start: bool = False) -> None:
        self.path = path
        self._offset = 0
        self._key: tuple[int, int] | None = None
        self._head = b""
        self._started = from_start

    def _identity(self) -> tuple[int, int] | None:
        try:
            info = self.path.stat()
        except OSError:
            return None
        return (info.st_dev, info.st_ino)

    def _read_head(self) -> bytes | None:
        try:
            with self.path.open("rb") as handle:
                return handle.read(HEAD_BYTES)
        except OSError:
            return None

    def read(self) -> Iterator[str]:
        identity = self._identity()
        if identity is None:
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        head = self._read_head()
        if head is None:
            return

        if not self._started:
            self._started = True
            self._key = identity
            self._offset = size
            self._head = head
            return

        common = min(len(head), len(self._head))
        replaced = head[:common] != self._head[:common]
        if identity != self._key or size < self._offset or replaced:
            self._key = identity
            self._offset = 0
        self._head = head
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
