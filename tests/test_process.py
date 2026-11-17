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
def test_the_spawned_watcher_inherits_no_descriptor_of_the_caller(tmp_path: Path, monkeypatch):
    (tmp_path / "sleeper.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(process, "SERVER_MODULE", "sleeper")
    reader, writer = os.pipe()
    os.set_inheritable(reader, True)
    os.set_inheritable(writer, True)
    log = tmp_path / "watcher.log"
    pid = process.spawn(tmp_path, [], "token", log)
    try:
        assert _wait_until(lambda: process.read_token(pid) == "token")
        assert set(os.listdir(f"/proc/{pid}/fd")) == {"0", "1", "2"}
        assert os.readlink(f"/proc/{pid}/fd/1") == str(log)
        assert os.readlink(f"/proc/{pid}/fd/2") == str(log)
        assert os.getsid(pid) == pid
    finally:
        os.close(reader)
        os.close(writer)
        process.terminate(pid, "token")


def test_the_spawn_actions_redirect_the_three_standard_streams(tmp_path: Path):
    if sys.platform == "win32":
        assert process.spawn_actions(tmp_path / "w.log") == []
        return
    actions = process.spawn_actions(tmp_path / "w.log")
    assert actions[0][:3] == (os.POSIX_SPAWN_OPEN, 0, os.devnull)
    assert actions[1][:3] == (os.POSIX_SPAWN_OPEN, 1, str(tmp_path / "w.log"))
    assert actions[2] == (os.POSIX_SPAWN_DUP2, 1, 2)
