from __future__ import annotations

from gluetun_rotate.forbidden import Source, Streaming, count_forbidden, describe, forbidden_source

UNO = "e8c1a821-d151-40df-8b7a-5b9cbf19d88f"
RESERVOARR_403 = (
    f"2026-09-13 13:58:04,112 +0200 ERROR live_proxy.manager Stream process error for channel "
    f"{UNO}: [delaybuf] upstream error HTTPError: HTTP Error 403: Forbidden; retry in 2s"
)
RESERVOARR_520 = RESERVOARR_403.replace("403: Forbidden", "520: <none>")
PROXY_403 = (
    "2026-09-13 13:58:05,000 +0200 ERROR live_proxy.input.http_streamer "
    "HTTP 403 from http://provider.example/live/u/p/202121.ts"
)


def test_a_reservoarr_403_names_the_channel():
    assert forbidden_source(RESERVOARR_403) == Source(channel=UNO)


def test_a_proxy_403_names_the_feed():
    assert forbidden_source(PROXY_403) == Source(feed="202121.ts")


def test_other_errors_and_lines_are_not_counted():
    assert forbidden_source(RESERVOARR_520) is None
    assert forbidden_source("2026-09-13 INFO something HTTP 4030 unrelated") is None


def test_counts_are_kept_per_source():
    counts = count_forbidden([RESERVOARR_403, RESERVOARR_403, PROXY_403, RESERVOARR_520])
    assert counts[Source(channel=UNO)] == 2
    assert counts[Source(feed="202121.ts")] == 1
    assert sum(counts.values()) == 3


def test_sources_are_described_with_the_channel_name_when_it_is_streaming():
    counts = count_forbidden([RESERVOARR_403, RESERVOARR_403, PROXY_403])
    streaming = [Streaming(channel=UNO, name="Sky Sport Uno FHD", feed="202121.ts")]
    assert describe(counts, streaming) == [
        {"channel": "Sky Sport Uno FHD", "feed": "202121.ts", "count": 2},
        {"channel": "Sky Sport Uno FHD", "feed": "202121.ts", "count": 1},
    ]


def test_a_source_no_longer_streaming_keeps_what_the_log_said():
    counts = count_forbidden([RESERVOARR_403, PROXY_403])
    assert describe(counts, []) == [
        {"channel": UNO, "feed": "", "count": 1},
        {"channel": "", "feed": "202121.ts", "count": 1},
    ]
