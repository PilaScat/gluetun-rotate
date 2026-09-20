from __future__ import annotations

from gluetun_rotate.forbidden import Streaming
from gluetun_rotate.viewers import describe_watched, from_the_provider, watched

PROVIDER = "http://z6i01r.example/live/user/pass/202121.ts"
SLATE = "http://127.0.0.1:9721/slate.ts"


def row(name: str, url: str, clients: int) -> Streaming:
    return Streaming(
        channel=name.lower(),
        name=name,
        feed=url.rsplit("/", 1)[-1],
        url=url,
        clients=clients,
    )


def test_a_stream_from_the_provider_counts() -> None:
    assert from_the_provider(PROVIDER)


def test_the_card_does_not_count() -> None:
    assert not from_the_provider(SLATE)
    assert not from_the_provider("http://localhost:9721/slate.ts")
    assert not from_the_provider("")


def test_only_channels_with_viewers_on_a_real_source() -> None:
    rows = [
        row("Sky | Sport Uno", PROVIDER, 2),
        row("Sky | Sport 260", SLATE, 1),
        row("DAZN | Web 1", PROVIDER, 0),
    ]
    assert [r.name for r in watched(rows)] == ["Sky | Sport Uno"]


def test_the_names_go_into_the_journal() -> None:
    rows = [row("Sky | Sport Uno", PROVIDER, 1), row("DAZN | Web 1", PROVIDER, 3)]
    assert describe_watched(watched(rows)) == "Sky | Sport Uno and DAZN | Web 1"
    assert describe_watched([]) == ""
