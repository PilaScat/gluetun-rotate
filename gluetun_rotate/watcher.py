from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from .constants import (
    ACCOUNTS_REFRESH_SECONDS,
    API_KEY_ENV,
    DEFAULT_API_URL,
    DEFAULT_GLUETUN_URL,
    GLUETUN_KEY_ENV,
    MAX_RECENT_EVENTS,
    MAX_ROTATIONS_PER_HOUR,
    PROBE_INTERVAL_SECONDS,
    REFUSALS_BEFORE_ROTATING,
    ROTATION_COOLDOWN_SECONDS,
)
from .gluetun import Gluetun, Rotation
from .journal import Journal
from .provider import Account, Dispatcharr, Probe, probe
from .web import ApiError

HOUR_SECONDS = 3600.0


class AccountSource(Protocol):
    def accounts(self) -> list[Account]: ...


class Rotator(Protocol):
    def rotate(self) -> Rotation: ...

    def start_if_stopped(self) -> bool: ...


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="gluetun_rotate")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--gluetun-url", default=DEFAULT_GLUETUN_URL)
    parser.add_argument("--journal", required=True)
    return parser.parse_args(argv)


class Watcher:
    def __init__(
        self,
        dispatcharr: AccountSource,
        gluetun: Rotator,
        journal: Journal,
        prober: Callable[[Account], Probe] = probe,
        interval_seconds: float = PROBE_INTERVAL_SECONDS,
        refusals: int = REFUSALS_BEFORE_ROTATING,
        cooldown_seconds: float = ROTATION_COOLDOWN_SECONDS,
        rotations_per_hour: int = MAX_ROTATIONS_PER_HOUR,
        accounts_refresh_seconds: float = ACCOUNTS_REFRESH_SECONDS,
    ) -> None:
        self._dispatcharr = dispatcharr
        self._gluetun = gluetun
        self._journal = journal
        self._prober = prober
        self._interval_seconds = interval_seconds
        self._refusals = max(refusals, 1)
        self._cooldown_seconds = cooldown_seconds
        self._rotations_per_hour = max(rotations_per_hour, 1)
        self._accounts_refresh_seconds = accounts_refresh_seconds
        self._accounts: list[Account] = []
        self._accounts_at: float | None = None
        self._accounts_failing = False
        self._reported_no_accounts = False
        self._streak = 0
        self._rotations: deque[float] = deque()
        self._tunnel_may_be_stopped = False
        self._stopping = threading.Event()

    def stop(self, *_: object) -> None:
        self._stopping.set()

    def run(self) -> int:
        self._journal.write(
            "started", interval_seconds=self._interval_seconds, refusals=self._refusals
        )
        while not self._stopping.is_set():
            self.tick_safely(time.monotonic())
            self._stopping.wait(self._interval_seconds)
        self._journal.write("stopped")
        return 0

    def tick_safely(self, now: float) -> None:
        try:
            self.tick(now)
        except Exception as error:
            self._journal.write("error", detail=f"{type(error).__name__}: {error}")

    def tick(self, now: float) -> None:
        self._restart_a_tunnel_left_stopped()
        accounts = self._current_accounts(now)
        if not accounts:
            return
        refused = [result for result in map(self._prober, accounts) if result.refused]
        if not refused:
            if self._streak >= self._refusals:
                self._journal.write("accepted", after_refusals=self._streak)
            self._streak = 0
            return
        self._streak += 1
        self._journal.write(
            "refused", streak=self._streak, probes=[result.describe() for result in refused]
        )
        if self._streak >= self._refusals:
            self._rotate(now)

    def _rotate(self, now: float) -> None:
        reason = self._held_back(now)
        if reason:
            self._journal.write("skipped", reason=reason)
            return
        self._rotations.append(now)
        try:
            rotation = self._gluetun.rotate()
        except ApiError as error:
            self._tunnel_may_be_stopped = True
            self._journal.write("failed", detail=str(error))
            return
        if not rotation.moved:
            self._journal.write(
                "failed",
                detail="the exit address did not change",
                before=rotation.before,
                after=rotation.after,
                stop_confirmed=rotation.stop_confirmed,
            )
            return
        self._streak = 0
        self._journal.write(
            "rotated",
            before=rotation.before,
            after=rotation.after,
            stop_confirmed=rotation.stop_confirmed,
            probes=[result.describe() for result in map(self._prober, self._accounts)],
        )

    def _restart_a_tunnel_left_stopped(self) -> None:
        if not self._tunnel_may_be_stopped:
            return
        try:
            restarted = self._gluetun.start_if_stopped()
        except ApiError:
            return
        self._tunnel_may_be_stopped = False
        if restarted:
            self._journal.write("restarted")

    def _held_back(self, now: float) -> str:
        while self._rotations and now - self._rotations[0] >= HOUR_SECONDS:
            self._rotations.popleft()
        if self._rotations and now - self._rotations[-1] < self._cooldown_seconds:
            return "cooling down after the last rotation"
        if len(self._rotations) >= self._rotations_per_hour:
            return "hourly limit reached"
        return ""

    def _current_accounts(self, now: float) -> list[Account]:
        due = (
            self._accounts_at is None
            or now - self._accounts_at >= self._accounts_refresh_seconds
        )
        if due:
            try:
                self._accounts = self._dispatcharr.accounts()
                self._accounts_at = now
                self._accounts_failing = False
            except ApiError as error:
                if not self._accounts_failing:
                    self._journal.write("api_error", where="accounts", detail=str(error))
                self._accounts_failing = True
        if not self._accounts and not self._accounts_failing and not self._reported_no_accounts:
            self._journal.write("skipped", reason="no active Xtream Codes account to ask")
            self._reported_no_accounts = True
        return self._accounts


def main(argv: Sequence[str] | None = None) -> int:
    options = arguments(argv)
    api_key = os.environ.get(API_KEY_ENV, "")
    gluetun_key = os.environ.get(GLUETUN_KEY_ENV, "")
    if not api_key or not gluetun_key:
        print(f"{API_KEY_ENV} and {GLUETUN_KEY_ENV} must both be set", file=sys.stderr)
        return 2
    watcher = Watcher(
        Dispatcharr(options.api_url, api_key),
        Gluetun(options.gluetun_url, gluetun_key),
        Journal(Path(options.journal), MAX_RECENT_EVENTS),
    )
    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, watcher.stop)
    return watcher.run()


if __name__ == "__main__":
    raise SystemExit(main())
