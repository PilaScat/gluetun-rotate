from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def load(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def save(path: Path, values: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(values), sort_keys=True, indent=1)
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise
    return dict(values)


def migrate(sources: Iterable[Path], target: Path) -> bool:
    if _holds_anything(target):
        return False
    for source in sources:
        if source.resolve() == target.resolve() or not _holds_anything(source):
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            for entry in list(source.iterdir()):
                os.rename(entry, target / entry.name)
        except OSError:
            return False
        with contextlib.suppress(OSError):
            source.rmdir()
        return True
    return False


def is_older(stored: object, current: str) -> bool:
    mine = _version(current)
    if mine is None:
        return False
    theirs = _version(stored)
    return theirs is None or theirs < mine


def started_version(values: Mapping[str, Any]) -> object:
    token = values.get("token")
    if token and values.get("version_token") == token:
        return values.get("version")
    return None


def _version(value: object) -> tuple[int, ...] | None:
    if value is None:
        return None
    match = VERSION_PATTERN.match(str(value).strip())
    return tuple(int(part) for part in match.groups()) if match else None


def _holds_anything(folder: Path) -> bool:
    try:
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False


def remember(
    path: Path, updates: Mapping[str, Any], clear: Iterable[str] = ()
) -> dict[str, Any]:
    values = load(path)
    values.update(updates)
    for key in clear:
        values.pop(key, None)
    return save(path, values)
