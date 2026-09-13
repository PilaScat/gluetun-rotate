from __future__ import annotations

import json
from pathlib import Path

from gluetun_rotate.gluetun import Rotation
from gluetun_rotate.journal import Journal
from gluetun_rotate.provider import Account, Probe
from gluetun_rotate.watcher import Watcher, main
from gluetun_rotate.web import ApiError

ACCOUNT = Account(
    name="Miglior IPTV",
    server_url="http://provider.example/",
    username="user",
    password="s3cret-pass",
    user_agent="TiviMate/5.1.6 (Android 12)",
)


class FakeDispatcharr:
    def __init__(self, accounts: list[Account] | None = None, fails: bool = False) -> None:
        self._accounts = [ACCOUNT] if accounts is None else accounts
        self.fails = fails

    def accounts(self) -> list[Account]:
        if self.fails:
            raise ApiError("GET /api/m3u/accounts/ failed: timed out")
        return list(self._accounts)


class FakeGluetun:
    def __init__(self) -> None:
        self.address = "203.0.113.10"
        self.rotations = 0
        self.moves = True
        self.fails = False
        self.stopped = False
        self.start_checks = 0

    def rotate(self) -> Rotation:
        if self.fails:
            self.stopped = True
            raise ApiError("PUT /v1/vpn/status returned 401")
        before = self.address
        self.rotations += 1
        if self.moves:
            self.address = f"198.51.100.{self.rotations}"
        return Rotation(before=before, after=self.address)

    def start_if_stopped(self) -> bool:
        self.start_checks += 1
        if not self.stopped:
            return False
        self.stopped = False
        return True


class Answers:
    def __init__(self, *statuses: int | None) -> None:
        self.statuses = list(statuses)
        self.last = statuses[-1] if statuses else 200

    def __call__(self, account: Account) -> Probe:
        status = self.statuses.pop(0) if self.statuses else self.last
        return Probe(account=account.name, status=status)


def build(
    tmp_path: Path, answers: Answers, dispatcharr: FakeDispatcharr | None = None
) -> tuple[Watcher, FakeGluetun, Journal]:
    gluetun = FakeGluetun()
    journal = Journal(tmp_path / "journal.jsonl", 200)
    watcher = Watcher(dispatcharr or FakeDispatcharr(), gluetun, journal, prober=answers)
    return watcher, gluetun, journal


def ticks(watcher: Watcher, count: int, start: float = 0.0, step: float = 120.0) -> float:
    now = start
    for _ in range(count):
        watcher.tick(now)
        now += step
    return now


def events(journal: Journal) -> list[str]:
    return [row["event"] for row in journal.read()]


def test_one_refusal_is_not_enough_to_rotate(tmp_path: Path):
    watcher, gluetun, _ = build(tmp_path, Answers(520, 200))
    ticks(watcher, 2)
    assert gluetun.rotations == 0


def test_two_refusals_in_a_row_rotate_the_exit_address(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520, 520, 200))
    ticks(watcher, 2)
    assert gluetun.rotations == 1
    rotated = journal.read()[-1]
    assert rotated["event"] == "rotated"
    assert rotated["before"] == "203.0.113.10"
    assert rotated["after"] == "198.51.100.1"
    assert rotated["probes"] == ["Miglior IPTV: HTTP 200"]


def test_an_accepted_probe_in_between_starts_the_count_again(tmp_path: Path):
    watcher, gluetun, _ = build(tmp_path, Answers(520, 200, 520, 200))
    ticks(watcher, 4)
    assert gluetun.rotations == 0


def test_a_provider_failing_on_its_own_never_moves_the_tunnel(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(507, 509, 403, 502, None))
    ticks(watcher, 10)
    assert gluetun.rotations == 0
    assert "refused" not in events(journal)


def test_a_second_rotation_waits_for_the_cooldown(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520))
    ticks(watcher, 4, step=120)
    assert gluetun.rotations == 1
    assert journal.read()[-1]["reason"] == "cooling down after the last rotation"
    ticks(watcher, 3, start=720, step=120)
    assert gluetun.rotations == 2


def test_no_more_than_three_rotations_an_hour(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520))
    ticks(watcher, 30, step=120)
    assert gluetun.rotations == 3
    assert "hourly limit reached" in [row.get("reason") for row in journal.read()]
    ticks(watcher, 10, start=3600 + 30 * 120, step=120)
    assert gluetun.rotations > 3


def test_a_tunnel_that_comes_back_on_the_same_address_is_a_failure(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520, 520))
    gluetun.moves = False
    ticks(watcher, 2)
    last = journal.read()[-1]
    assert last["event"] == "failed"
    assert last["detail"] == "the exit address did not change"


def test_a_control_server_error_is_recorded(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520, 520))
    gluetun.fails = True
    ticks(watcher, 2)
    last = journal.read()[-1]
    assert last["event"] == "failed"
    assert "401" in last["detail"]


def test_a_tunnel_left_stopped_by_a_failed_rotation_is_started_again(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520, 520, 200))
    gluetun.fails = True
    ticks(watcher, 3)
    names = events(journal)
    assert names.index("restarted") == names.index("failed") + 1
    assert gluetun.stopped is False
    ticks(watcher, 3, start=360)
    assert gluetun.start_checks == 1


def test_a_tunnel_is_never_started_without_a_rotation_of_ours(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(200))
    gluetun.stopped = True
    ticks(watcher, 5)
    assert gluetun.start_checks == 0
    assert "restarted" not in events(journal)


def test_an_unreachable_dispatcharr_is_recorded_once(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520), FakeDispatcharr(fails=True))
    ticks(watcher, 20, step=900)
    assert events(journal) == ["api_error"]
    assert gluetun.rotations == 0


def test_without_an_xtream_account_there_is_nothing_to_ask(tmp_path: Path):
    watcher, gluetun, journal = build(tmp_path, Answers(520), FakeDispatcharr(accounts=[]))
    ticks(watcher, 5)
    assert events(journal) == ["skipped"]
    assert gluetun.rotations == 0


def test_the_journal_never_holds_the_account_credentials(tmp_path: Path):
    watcher, _, journal = build(tmp_path, Answers(520, 520, 520, None))
    ticks(watcher, 8)
    written = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert "s3cret-pass" not in written
    assert all(json.loads(line) for line in written.splitlines())


def test_the_watcher_refuses_to_start_without_both_keys(monkeypatch):
    monkeypatch.delenv("GLUETUN_ROTATE_API_KEY", raising=False)
    monkeypatch.setenv("GLUETUN_ROTATE_GLUETUN_KEY", "k")
    assert main(["--journal", "x"]) == 2
