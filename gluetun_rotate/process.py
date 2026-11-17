from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from .constants import MAX_LOG_BYTES, RUN_TOKEN_ENV, TERMINATE_GRACE_SECONDS
from .constants import WATCHER_MODULE as SERVER_MODULE


def resolve_interpreter() -> str:
    executable = Path(sys.executable or "")
    candidates: list[Path] = []
    if executable.name.lower().startswith("uwsgi"):
        candidates += [executable.with_name("python3"), executable.with_name("python")]
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        candidates += [Path(venv) / "bin" / "python3", Path(venv) / "bin" / "python"]
    if executable.name and not executable.name.lower().startswith("uwsgi"):
        candidates.append(executable)
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    if executable.name:
        return str(executable)
    raise RuntimeError("No Python interpreter could be located to start the watcher.")


def prepend_pythonpath(existing: str | None, entry: str) -> str:
    parts = [part for part in (existing or "").split(os.pathsep) if part]
    if entry in parts:
        return os.pathsep.join(parts)
    return os.pathsep.join([entry, *parts])


def _trim_log(log_path: Path) -> None:
    try:
        if log_path.is_file() and log_path.stat().st_size > MAX_LOG_BYTES:
            log_path.unlink()
    except OSError:
        pass


def spawn(
    base_dir: Path,
    arguments: Sequence[str],
    run_token: str,
    log_path: Path,
    extra_env: Mapping[str, str] | None = None,
) -> int:
    command = [resolve_interpreter(), "-m", SERVER_MODULE, *arguments]

    environment = os.environ.copy()
    environment["PYTHONPATH"] = prepend_pythonpath(
        environment.get("PYTHONPATH"), str(base_dir)
    )
    environment[RUN_TOKEN_ENV] = run_token
    environment.update(dict(extra_env or {}))
    environment.setdefault("PYTHONUNBUFFERED", "1")
    environment["PYTHONSAFEPATH"] = "1"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    _trim_log(log_path)
    if sys.platform == "win32":
        return _popen(command, environment, base_dir, log_path)
    return os.posix_spawn(
        command[0], command, environment, file_actions=spawn_actions(log_path), setsid=True
    )


def spawn_actions(log_path: Path) -> list[tuple]:
    if sys.platform == "win32":
        return []
    actions: list[tuple] = [
        (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
        (os.POSIX_SPAWN_OPEN, 1, str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666),
        (os.POSIX_SPAWN_DUP2, 1, 2),
    ]
    close_from = getattr(os, "POSIX_SPAWN_CLOSEFROM", None)
    if close_from is not None:
        actions.append((close_from, 3))
    return actions


def _popen(
    command: Sequence[str], environment: Mapping[str, str], base_dir: Path, log_path: Path
) -> int:
    with log_path.open("ab") as handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=dict(environment),
            cwd=str(base_dir),
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    return process.pid


def read_token(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/environ", "rb") as handle:
            entries = handle.read().split(b"\0")
    except OSError:
        return None
    prefix = f"{RUN_TOKEN_ENV}=".encode()
    for entry in entries:
        if entry.startswith(prefix):
            return entry[len(prefix) :].decode("utf-8", "ignore")
    return None


def read_cmdline_parts(pid: int) -> list[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        return []
    return [part.decode("utf-8", "ignore") for part in raw.split(b"\0") if part]


def read_cmdline(pid: int) -> str | None:
    parts = read_cmdline_parts(pid)
    return " ".join(parts) if parts else None


def find_servers() -> list[int]:
    found: list[int] = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if SERVER_MODULE in read_cmdline_parts(pid):
            found.append(pid)
    return found


def terminate_strays(keep_pid: object = None) -> int:
    spared = coerce_pid(keep_pid)
    stopped = 0
    for pid in find_servers():
        if pid == spared:
            continue
        if terminate(pid):
            stopped += 1
    return stopped


def matches_token(pid: int, expected_token: str) -> bool:
    token = read_token(pid)
    if token is not None:
        return token == expected_token
    cmdline = read_cmdline(pid)
    if cmdline is not None:
        return SERVER_MODULE in cmdline
    return False


def coerce_pid(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
    return None


def is_running(pid: object, expected_token: str | None = None) -> bool:
    target = coerce_pid(pid)
    if target is None:
        return False
    if expected_token and not matches_token(target, expected_token):
        return False
    try:
        finished, _ = os.waitpid(target, getattr(os, "WNOHANG", 0))
        if finished == target:
            return False
    except ChildProcessError:
        pass
    except OSError:
        return False
    if is_zombie(target):
        return False
    try:
        os.kill(target, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_zombie(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            raw = handle.read()
    except OSError:
        return False
    fields = raw.rpartition(b")")[2].split()
    return bool(fields) and fields[0] == b"Z"


def reap(pid: int) -> None:
    try:
        while True:
            finished, _ = os.waitpid(pid, getattr(os, "WNOHANG", 0))
            if finished in (0, pid):
                break
    except (ChildProcessError, OSError):
        pass


def _send(pid: int, number: int) -> None:
    if os.name != "nt" and hasattr(os, "killpg"):
        try:
            os.killpg(pid, number)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    os.kill(pid, number)


def terminate(
    pid: object,
    expected_token: str | None = None,
    grace_seconds: float = TERMINATE_GRACE_SECONDS,
) -> bool:
    target = coerce_pid(pid)
    if target is None or not is_running(target, expected_token):
        return False

    try:
        _send(target, signal.SIGTERM)
    except ProcessLookupError:
        return False

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not is_running(target):
            break
        time.sleep(0.25)
    else:
        kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        with contextlib.suppress(ProcessLookupError, OSError):
            _send(target, kill_signal)

    reap(target)
    return True
