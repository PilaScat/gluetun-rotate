from __future__ import annotations

import io
import json
import urllib.error

import pytest

from gluetun_rotate import web
from gluetun_rotate.gluetun import Gluetun, Rotation
from gluetun_rotate.web import ApiError, fetch


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeGluetun(Gluetun):
    def __init__(self, addresses: list[str], stops: bool = True) -> None:
        self.clock = Clock()
        super().__init__(
            "http://127.0.0.1:8000", "key", clock=self.clock, sleep=self.clock.sleep
        )
        self.addresses = addresses
        self.stops = stops
        self.status = "running"
        self.calls: list[tuple[str, str, object]] = []
        self.running_failures = 0
        self.stop_times_out = False

    def _call(self, method: str, path: str, body: dict[str, object] | None = None) -> object:
        self.calls.append((method, path, body))
        if path == "/v1/publicip/ip":
            address = self.addresses.pop(0) if len(self.addresses) > 1 else self.addresses[0]
            return {"public_ip": address}
        if method == "GET":
            return {"status": self.status}
        if body == {"status": "running"} and self.running_failures:
            self.running_failures -= 1
            raise ApiError("PUT /v1/vpn/status failed: refused")
        if body == {"status": "stopped"} and self.stop_times_out:
            self.status = "stopped"
            raise ApiError("PUT /v1/vpn/status failed: timed out")
        if body == {"status": "stopped"} and not self.stops:
            return {"outcome": "running"}
        self.status = str((body or {}).get("status"))
        return {"outcome": self.status}


def puts(gluetun: FakeGluetun) -> list[object]:
    return [body for method, _, body in gluetun.calls if method == "PUT"]


def test_a_rotation_stops_the_tunnel_starts_it_and_reports_the_new_address():
    gluetun = FakeGluetun(["203.0.113.10", "203.0.113.10", "198.51.100.20"])
    rotation = gluetun.rotate()
    assert puts(gluetun) == [{"status": "stopped"}, {"status": "running"}]
    assert rotation == Rotation(before="203.0.113.10", after="198.51.100.20")
    assert rotation.moved is True


def test_the_tunnel_is_started_again_even_when_it_never_reports_stopped():
    gluetun = FakeGluetun(["1.1.1.1", "2.2.2.2"], stops=False)
    rotation = gluetun.rotate()
    assert puts(gluetun)[-1] == {"status": "running"}
    assert rotation.stop_confirmed is False


def test_a_stop_request_that_times_out_still_starts_the_tunnel_again():
    gluetun = FakeGluetun(["1.1.1.1", "2.2.2.2"])
    gluetun.stop_times_out = True
    with pytest.raises(ApiError):
        gluetun.rotate()
    assert puts(gluetun)[-1] == {"status": "running"}
    assert gluetun.status == "running"


def test_a_stopped_tunnel_is_started_and_a_running_one_left_alone():
    gluetun = FakeGluetun(["1.1.1.1"])
    assert gluetun.start_if_stopped() is False
    assert puts(gluetun) == []
    gluetun.status = "stopped"
    assert gluetun.start_if_stopped() is True
    assert puts(gluetun) == [{"status": "running"}]


def test_starting_the_tunnel_again_is_retried():
    gluetun = FakeGluetun(["1.1.1.1", "2.2.2.2"])
    gluetun.running_failures = 2
    gluetun.rotate()
    assert gluetun.status == "running"


def test_an_address_that_never_changes_is_reported_as_not_moved():
    gluetun = FakeGluetun(["1.1.1.1"])
    rotation = gluetun.rotate()
    assert rotation.moved is False
    assert gluetun.clock.now >= 90


class Opened:
    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self.payload = payload

    def __enter__(self) -> Opened:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_the_control_server_is_called_with_the_key_and_a_json_body(monkeypatch):
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        return Opened(200, b'{"outcome":"stopped"}')

    monkeypatch.setattr(web.urllib.request, "urlopen", urlopen)
    Gluetun("http://127.0.0.1:8000/", "secret").set_vpn("stopped")
    request = seen[0]
    assert request.full_url == "http://127.0.0.1:8000/v1/vpn/status"
    assert request.get_method() == "PUT"
    assert request.get_header("X-api-key") == "secret"
    assert json.loads(request.data) == {"status": "stopped"}


def test_an_http_error_comes_back_as_a_status_rather_than_an_exception(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 520, "", {}, io.BytesIO(b""))

    monkeypatch.setattr(web.urllib.request, "urlopen", urlopen)
    assert fetch("http://provider/player_api.php?username=u&password=p").status == 520


def test_a_network_failure_never_repeats_the_address_it_was_sent_to(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(web.urllib.request, "urlopen", urlopen)
    with pytest.raises(ApiError) as caught:
        fetch("http://provider/player_api.php?username=u&password=secret")
    assert "secret" not in str(caught.value)
    assert "timed out" in str(caught.value)
