from __future__ import annotations

import re
import urllib.parse
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

RESERVOARR_FORBIDDEN = re.compile(
    r"Stream process error for channel (?P<channel>[0-9a-f-]{36}): .*\bHTTP Error 403\b"
)
PROXY_FORBIDDEN = re.compile(r"\bHTTP 403 from (?P<url>\S+)")


@dataclass(frozen=True)
class Source:
    channel: str = ""
    feed: str = ""


@dataclass(frozen=True)
class Streaming:
    channel: str
    name: str
    feed: str


def feed_of(url: str) -> str:
    return urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]


def forbidden_source(line: str) -> Source | None:
    found = RESERVOARR_FORBIDDEN.search(line)
    if found:
        return Source(channel=found.group("channel"))
    found = PROXY_FORBIDDEN.search(line)
    if found:
        return Source(feed=feed_of(found.group("url")))
    return None


def count_forbidden(lines: Iterable[str]) -> Counter[Source]:
    counts: Counter[Source] = Counter()
    for line in lines:
        source = forbidden_source(line)
        if source is not None:
            counts[source] += 1
    return counts


def describe(counts: Counter[Source], streaming: Iterable[Streaming]) -> list[dict]:
    by_channel = {row.channel: row for row in streaming}
    by_feed = {row.feed: row for row in by_channel.values() if row.feed}
    rows = []
    for source, count in counts.most_common():
        match = by_channel.get(source.channel) or by_feed.get(source.feed)
        rows.append(
            {
                "channel": match.name if match else source.channel,
                "feed": match.feed if match else source.feed,
                "count": count,
            }
        )
    return rows
