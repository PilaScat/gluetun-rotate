from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

try:
    from .gluetun_rotate import process
    from .gluetun_rotate import state as state_module
    from .gluetun_rotate.constants import (
        API_KEY_ENV,
        DEFAULT_API_URL,
        DEFAULT_GLUETUN_URL,
        GLUETUN_KEY_ENV,
        MAX_RECENT_EVENTS,
        PLUGIN_DESCRIPTION,
        PLUGIN_NAME,
        PLUGIN_SLUG,
        PLUGIN_VERSION,
        SUPERVISE_INTERVAL_SECONDS,
        SUPERVISE_RETRY_SECONDS,
    )
    from .gluetun_rotate.gluetun import Gluetun
    from .gluetun_rotate.journal import Journal
    from .gluetun_rotate.provider import Dispatcharr, probe
    from .gluetun_rotate.web import ApiError
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gluetun_rotate import process
    from gluetun_rotate import state as state_module
    from gluetun_rotate.constants import (
        API_KEY_ENV,
        DEFAULT_API_URL,
        DEFAULT_GLUETUN_URL,
        GLUETUN_KEY_ENV,
        MAX_RECENT_EVENTS,
        PLUGIN_DESCRIPTION,
        PLUGIN_NAME,
        PLUGIN_SLUG,
        PLUGIN_VERSION,
        SUPERVISE_INTERVAL_SECONDS,
        SUPERVISE_RETRY_SECONDS,
    )
    from gluetun_rotate.gluetun import Gluetun
    from gluetun_rotate.journal import Journal
    from gluetun_rotate.provider import Dispatcharr, probe
    from gluetun_rotate.web import ApiError

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR.parent / "_data" / PLUGIN_SLUG
LEGACY_RUNTIME_DIR = BASE_DIR / ".runtime"
STATE_FILE = "state.json"
JOURNAL_FILE = "gluetun-rotate.jsonl"
LOG_FILE = "watcher.log"

DETACHING_REASONS = frozenset({"disable", "delete"})
FAILED_EVENTS = frozenset({"failed", "api_error", "error"})

def _read_manifest() -> dict[str, Any]:
    try:
        with (BASE_DIR / "plugin.json").open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


_MANIFEST = _read_manifest()


def _close_database_connection() -> None:
    try:
        from django.db import connection
    except ImportError:
        return
    connection.close()


def _as_text(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _as_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "on", "yes"}


class Plugin:
    name = _MANIFEST.get("name", PLUGIN_NAME)
    version = _MANIFEST.get("version", PLUGIN_VERSION)
    description = _MANIFEST.get("description", PLUGIN_DESCRIPTION)
    author = _MANIFEST.get("author", "")
    help_url = _MANIFEST.get("help_url", "")
    fields = _MANIFEST.get("fields", [])
    actions = _MANIFEST.get("actions", [])

    def __init__(self) -> None:
        self._runtime = RUNTIME_DIR

    @property
    def _state_path(self) -> Path:
        return self._runtime / STATE_FILE

    @property
    def _journal_path(self) -> Path:
        return self._runtime / JOURNAL_FILE

    @property
    def _log_path(self) -> Path:
        return self._runtime / LOG_FILE

    def _locate(self, context: dict) -> None:
        given = str(context.get("data_dir") or "").strip()
        self._runtime = Path(given) if given else RUNTIME_DIR
        state_module.migrate([RUNTIME_DIR, LEGACY_RUNTIME_DIR], self._runtime)

    def run(self, action: str, params: dict, context: dict) -> dict:
        handlers = {
            "apply": self._apply,
            "status": self._status,
            "test": self._test,
            "remove": self._remove,
        }
        handler = handlers.get((action or "").strip().lower())
        if handler is None:
            return {"status": "error", "message": f"Unknown action '{action}'."}
        self._locate(dict(context or {}))
        try:
            return handler(dict(context or {}))
        except Exception as exc:
            logger.exception("Gluetun Rotate action '%s' failed", action)
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}

    def stop(self, context: dict | None = None) -> dict:
        context = dict(context or {})
        self._locate(context)
        stopped = self._stop_watcher()
        if str(context.get("reason") or "") in DETACHING_REASONS:
            self._remember({}, clear=["pid", "token", "applied"])
        else:
            self._remember({}, clear=["pid", "token"])
        return {
            "status": "ok",
            "message": "Watcher stopped." if stopped else "Watcher was not running.",
        }

    def _apply(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        missing = self._missing_keys(settings)
        if missing:
            return {"status": "error", "message": missing}
        self._stop_watcher()
        self._start(settings)
        self._remember({"applied": True})
        return {
            "status": "ok",
            "message": "Watcher running: it asks the provider every two minutes.",
        }

    def _status(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        state = self._state()
        running = process.is_running(state.get("pid"), state.get("token"))
        records = Journal(self._journal_path, MAX_RECENT_EVENTS).read()
        rotations = [row for row in records if row.get("event") == "rotated"]
        failed = [row for row in records if row.get("event") in FAILED_EVENTS]
        forbidden = [row for row in records if row.get("event") == "forbidden"]

        if not state.get("applied"):
            headline = "Not applied yet. Fill in both keys and press Apply."
        else:
            headline = "Watcher is running." if running else "Watcher is not running."
        parts = [headline, self._exit_address(settings)]
        if rotations:
            last = rotations[-1]
            parts.append(f"Last rotation: {last.get('before')} to {last.get('after')}.")
        else:
            parts.append("No rotation yet.")
        if failed:
            parts.append(f"{len(failed)} error(s) in the journal.")
        if forbidden:
            last = ", ".join(
                f"{row.get('channel')} x{row.get('count')}"
                for row in forbidden[-1].get("channels") or []
            )
            parts.append(f"HTTP 403 in {len(forbidden)} round(s), last on {last}.")

        return {
            "status": "ok" if running or not state.get("applied") else "error",
            "message": " ".join(part for part in parts if part),
            "running": running,
            "rotations": len(rotations),
            "forbidden_rounds": len(forbidden),
            "events": records[-MAX_RECENT_EVENTS:],
        }

    def _test(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        key = _as_text(settings.get("api_key"), "")
        if not key:
            return {"status": "error", "message": "A Dispatcharr API key is required."}
        accounts = Dispatcharr(DEFAULT_API_URL, key).accounts()
        if not accounts:
            return {"status": "error", "message": "No active Xtream Codes account to ask."}
        count_resets = _as_flag(settings.get("count_resets"))
        results = [probe(account, count_resets=count_resets) for account in accounts]
        answers = "; ".join(result.describe() for result in results)
        verdict = (
            "The provider refuses this address."
            if any(result.refused for result in results)
            else "The provider accepts this address."
        )
        return {
            "status": "ok",
            "message": " ".join(
                part for part in (verdict, answers + ".", self._exit_address(settings)) if part
            ),
            "refused": any(result.refused for result in results),
        }

    def on_leader_acquired(self, context: dict) -> None:
        context = dict(context or {})
        self._locate(context)
        snapshot = dict(context.get("settings") or {})
        reader = context.get("get_settings")

        def read_settings() -> dict:
            return dict(reader() or {}) if callable(reader) else snapshot

        supervise = partial(self._supervise, read_settings=read_settings)
        context["start_service"](supervise, name="watcher")

    def _supervise(self, stop_event: threading.Event, read_settings: Callable[[], dict]) -> None:
        reported = ""
        while not stop_event.is_set():
            problem = self._supervise_once(stop_event, read_settings)
            if problem and problem != reported:
                Journal(self._journal_path, MAX_RECENT_EVENTS).write("error", detail=problem)
            reported = problem
            stop_event.wait(SUPERVISE_RETRY_SECONDS if problem else SUPERVISE_INTERVAL_SECONDS)
        process.reap_spawned()

    def _supervise_once(
        self, stop_event: threading.Event, read_settings: Callable[[], dict]
    ) -> str:
        try:
            process.reap_spawned()
            return self._keep_running(stop_event, read_settings)
        except Exception as exc:
            logger.exception("Gluetun Rotate could not keep the watcher running")
            return f"{type(exc).__name__}: {exc}"
        finally:
            _close_database_connection()

    def _keep_running(self, stop_event: threading.Event, read_settings: Callable[[], dict]) -> str:
        if self._superseded():
            return ""
        state = self._state()
        if not state.get("applied") or self._current(state):
            return ""
        settings = read_settings()
        missing = self._missing_keys(settings)
        if missing:
            return missing
        if stop_event.is_set() or self._replaced_meanwhile():
            return ""
        if not self._state().get("applied"):
            return ""
        self._start(settings)
        return ""

    def _superseded(self) -> bool:
        return state_module.is_older(PLUGIN_VERSION, _read_manifest().get("version"))

    def _remove(self, context: dict) -> dict:
        stopped = self._stop_watcher()
        self._remember({}, clear=["pid", "token", "applied"])
        return {
            "status": "ok",
            "message": "Watcher stopped." if stopped else "Watcher was not running.",
        }

    def _missing_keys(self, settings: dict) -> str:
        if not _as_text(settings.get("api_key"), ""):
            return "A Dispatcharr API key is required."
        if not _as_text(settings.get("gluetun_api_key"), ""):
            return "A Gluetun control server key is required."
        return ""

    def _exit_address(self, settings: dict) -> str:
        key = _as_text(settings.get("gluetun_api_key"), "")
        if not key:
            return ""
        try:
            address = Gluetun(self._gluetun_url(settings), key).public_ip()
        except ApiError as error:
            return f"Gluetun did not answer: {error}."
        return f"Exit address {address}." if address else ""

    def _gluetun_url(self, settings: dict) -> str:
        return _as_text(settings.get("gluetun_url"), DEFAULT_GLUETUN_URL)

    def _arguments(self, settings: dict) -> list[str]:
        arguments = [
            "--api-url",
            DEFAULT_API_URL,
            "--gluetun-url",
            self._gluetun_url(settings),
            "--journal",
            str(self._journal_path),
        ]
        if _as_flag(settings.get("count_resets")):
            arguments.append("--count-resets")
        return arguments

    def _start(self, settings: dict) -> None:
        process.terminate_strays()
        token = uuid.uuid4().hex
        pid = process.spawn(
            BASE_DIR,
            self._arguments(settings),
            token,
            self._log_path,
            extra_env={
                API_KEY_ENV: _as_text(settings.get("api_key"), ""),
                GLUETUN_KEY_ENV: _as_text(settings.get("gluetun_api_key"), ""),
            },
        )
        self._remember(
            {
                "pid": pid,
                "token": token,
                "started_at": time.time(),
                "version": PLUGIN_VERSION,
                "version_token": token,
            }
        )
        if not self._settled(pid, token):
            process.terminate(pid)
            self._remember({}, clear=["pid", "token"])
            raise RuntimeError(f"The watcher exited on startup. See {self._log_path}.")

    def _settled(self, pid: int, token: str, seconds: float = 3.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not process.is_running(pid, token):
                return False
            time.sleep(0.25)
        return True

    def _stop_watcher(self) -> bool:
        state = self._state()
        stopped = process.terminate(state.get("pid"), state.get("token"))
        strays = process.terminate_strays()
        return stopped or bool(strays)

    def _older(self, state: dict) -> bool:
        return state_module.is_older(state_module.started_version(state), PLUGIN_VERSION)

    def _current(self, state: dict) -> bool:
        return process.is_running(state.get("pid"), state.get("token")) and not self._older(state)

    def _replaced_meanwhile(self) -> bool:
        latest = self._state()
        if self._current(latest):
            return True
        if process.is_running(latest.get("pid"), latest.get("token")):
            logger.info(
                "Gluetun Rotate replaces the watcher started by %s",
                state_module.started_version(latest) or "an older version",
            )
        return False

    def _state(self) -> dict:
        return state_module.load(self._state_path)

    def _remember(self, updates: dict, clear: list[str] | None = None) -> dict:
        return state_module.remember(self._state_path, updates, clear or [])
