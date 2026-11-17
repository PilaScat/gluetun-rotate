from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gluetun_rotate import process

linux_only = pytest.mark.skipif(not os.path.isdir("/proc"), reason="needs /proc")


def _wait_until(check, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


@linux_only
def test_a_finished_child_nobody_reaped_counts_as_gone():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        assert _wait_until(lambda: process.is_zombie(child.pid))
        os.kill(child.pid, 0)
    finally:
        child.wait()


@linux_only
def test_a_live_process_is_not_a_zombie():
    assert process.is_zombie(os.getpid()) is False


def test_an_unknown_pid_is_not_a_zombie():
    assert process.is_zombie(2**22 + 7) is False


@linux_only
@pytest.mark.parametrize("close_from", [True, False])
def test_the_spawned_watcher_inherits_no_descriptor_of_the_caller(
    tmp_path: Path, monkeypatch, close_from
):
    if not close_from:
        monkeypatch.delattr(os, "POSIX_SPAWN_CLOSEFROM", raising=False)
    elif not hasattr(os, "POSIX_SPAWN_CLOSEFROM"):
        pytest.skip("POSIX_SPAWN_CLOSEFROM needs Python 3.13")
    (tmp_path / "sleeper.py").write_text(
        "import time\nprint('ready', flush=True)\ntime.sleep(30)\n", encoding="utf-8"
    )
    monkeypatch.setattr(process, "SERVER_MODULE", "sleeper")
    reader, writer = os.pipe()
    os.set_inheritable(reader, True)
    os.set_inheritable(writer, True)
    log = tmp_path / "watcher.log"
    pid = process.spawn(tmp_path, [], "token", log)
    try:
        assert _wait_until(lambda: log.is_file() and "ready" in log.read_text())
        assert set(os.listdir(f"/proc/{pid}/fd")) == {"0", "1", "2"}
        assert os.readlink(f"/proc/{pid}/fd/1") == str(log)
        assert os.readlink(f"/proc/{pid}/fd/2") == str(log)
        assert os.getsid(pid) == pid
    finally:
        os.close(reader)
        os.close(writer)
        process.terminate(pid, "token")


@linux_only
def test_spawn_returns_once_the_new_process_carries_its_token(tmp_path: Path, monkeypatch):
    (tmp_path / "sleeper.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(process, "SERVER_MODULE", "sleeper")
    for round_number in range(10):
        token = f"token-{round_number}"
        pid = process.spawn(tmp_path, [], token, tmp_path / "watcher.log")
        try:
            assert process.read_token(pid) == token
        finally:
            process.terminate(pid, token)


@linux_only
def test_a_spawned_process_that_ends_is_reaped_by_the_process_that_started_it(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "quick.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(process, "SERVER_MODULE", "quick")
    pid = process.spawn(tmp_path, [], "token", tmp_path / "watcher.log")
    assert _wait_until(lambda: process.is_zombie(pid))
    process.reap_spawned()
    assert not os.path.exists(f"/proc/{pid}")


def test_the_spawn_actions_redirect_the_three_standard_streams(tmp_path: Path):
    if sys.platform == "win32":
        assert process.spawn_actions(tmp_path / "w.log") == []
        return
    actions = process.spawn_actions(tmp_path / "w.log")
    assert actions[0][:3] == (os.POSIX_SPAWN_OPEN, 0, os.devnull)
    assert actions[1][:3] == (os.POSIX_SPAWN_OPEN, 1, str(tmp_path / "w.log"))
    assert actions[2] == (os.POSIX_SPAWN_DUP2, 1, 2)
