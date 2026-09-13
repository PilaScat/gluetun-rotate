from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .constants import GLUETUN_POLL_SECONDS, NEW_ADDRESS_TIMEOUT_SECONDS, VPN_STOP_TIMEOUT_SECONDS
from .web import ApiError, request_json

RESTART_ATTEMPTS = 3


@dataclass(frozen=True)
class Rotation:
    before: str
    after: str

    @property
    def moved(self) -> bool:
        return bool(self.after) and self.after != self.before


class Gluetun:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        poll_seconds: float = GLUETUN_POLL_SECONDS,
        stop_timeout: float = VPN_STOP_TIMEOUT_SECONDS,
        address_timeout: float = NEW_ADDRESS_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self._clock = clock
        self._sleep = sleep
        self._poll_seconds = poll_seconds
        self._stop_timeout = stop_timeout
        self._address_timeout = address_timeout

    def public_ip(self) -> str:
        payload = self._call("GET", "/v1/publicip/ip")
        return str(payload.get("public_ip") or "") if isinstance(payload, dict) else ""

    def vpn_status(self) -> str:
        payload = self._call("GET", "/v1/vpn/status")
        return str(payload.get("status") or "") if isinstance(payload, dict) else ""

    def set_vpn(self, status: str) -> None:
        self._call("PUT", "/v1/vpn/status", {"status": status})

    def rotate(self) -> Rotation:
        before = self.public_ip()
        self.set_vpn("stopped")
        try:
            self._wait_until(lambda: self.vpn_status() == "stopped", self._stop_timeout)
        finally:
            self._start_again()
        return Rotation(before=before, after=self._wait_for_new_address(before))

    def _start_again(self) -> None:
        for attempt in range(RESTART_ATTEMPTS):
            try:
                self.set_vpn("running")
                return
            except ApiError:
                if attempt == RESTART_ATTEMPTS - 1:
                    raise
                self._sleep(self._poll_seconds)

    def _wait_until(self, done: Callable[[], bool], timeout: float) -> bool:
        deadline = self._clock() + timeout
        while True:
            try:
                if done():
                    return True
            except ApiError:
                pass
            if self._clock() >= deadline:
                return False
            self._sleep(self._poll_seconds)

    def _wait_for_new_address(self, before: str) -> str:
        deadline = self._clock() + self._address_timeout
        while True:
            try:
                address = self.public_ip()
            except ApiError:
                address = ""
            if (address and address != before) or self._clock() >= deadline:
                return address
            self._sleep(self._poll_seconds)

    def _call(self, method: str, path: str, body: dict[str, object] | None = None) -> object:
        return request_json(
            self.base_url, path, method, headers={"X-API-Key": self.api_key}, body=body
        )
