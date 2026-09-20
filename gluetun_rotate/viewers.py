from __future__ import annotations

import urllib.parse
from collections.abc import Iterable

from .forbidden import Streaming

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def from_the_provider(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return bool(host) and host not in LOCAL_HOSTS


def watched(rows: Iterable[Streaming]) -> list[Streaming]:
    return [row for row in rows if row.clients > 0 and from_the_provider(row.url)]


def describe_watched(rows: Iterable[Streaming]) -> str:
    names = [row.name or row.channel for row in rows]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"
