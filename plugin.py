from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
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
        HEARTBEAT_INTERVAL_SECONDS,
        MAX_RECENT_EVENTS,
        PLUGIN_DESCRIPTION,
        PLUGIN_NAME,
        PLUGIN_VERSION,
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
        HEARTBEAT_INTERVAL_SECONDS,
        MAX_RECENT_EVENTS,
        PLUGIN_DESCRIPTION,
        PLUGIN_NAME,
        PLUGIN_VERSION,
    )
    from gluetun_rotate.gluetun import Gluetun
    from gluetun_rotate.journal import Journal
    from gluetun_rotate.provider import Dispatcharr, probe
    from gluetun_rotate.web import ApiError

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / ".runtime"
STATE_PATH = RUNTIME_DIR / "state.json"
JOURNAL_PATH = RUNTIME_DIR / "gluetun-rotate.jsonl"
LOG_PATH = RUNTIME_DIR / "watcher.log"

DETACHING_REASONS = frozenset({"disable", "delete"})
FAILED_EVENTS = frozenset({"failed", "api_error", "error"})

_heartbeat_lock = threading.Lock()
_heartbeat_checked_at = 0.0


def _read_manifest() -> dict[str, Any]:
    try:
        with (BASE_DIR / "plugin.json").open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


_MANIFEST = _read_manifest()


def _running_inside_uwsgi() -> bool:
    try:
        import uwsgi  # noqa: F401
    except ImportError:
        return False
    return True


def _as_text(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


class Plugin:
    name = _MANIFEST.get("name", PLUGIN_NAME)
    version = _MANIFEST.get("version", PLUGIN_VERSION)
    description = _MANIFEST.get("description", PLUGIN_DESCRIPTION)
    author = _MANIFEST.get("author", "")
    help_url = _MANIFEST.get("help_url", "")
    fields = _MANIFEST.get("fields", [])
    actions = _MANIFEST.get("actions", [])

    def run(self, action: str, params: dict, context: dict) -> dict:
        handlers = {
            "apply": self._apply,
            "status": self._status,
            "test": self._test,
            "restart": self._restart,
            "remove": self._remove,
        }
        handler = handlers.get((action or "").strip().lower())
        if handler is None:
            return {"status": "error", "message": f"Unknown action '{action}'."}
        try:
            return handler(dict(context or {}))
        except Exception as exc:
            logger.exception("Gluetun Rotate action '%s' failed", action)
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}

    def stop(self, context: dict | None = None) -> dict:
        context = dict(context or {})
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
        records = Journal(JOURNAL_PATH, MAX_RECENT_EVENTS).read()
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
        results = [probe(account) for account in accounts]
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

    def _restart(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        state = self._state()
        if not state.get("applied"):
            return {"status": "ok", "message": "Nothing to do: not applied."}
        if not _running_inside_uwsgi():
            return {
                "status": "ok",
                "message": "Skipped: the watcher only starts in the Dispatcharr web process.",
            }
        if not self._heartbeat_due():
            return {"status": "ok", "message": "Checked recently."}
        if process.is_running(state.get("pid"), state.get("token")):
            return {"status": "ok", "message": "Watcher is running."}
        missing = self._missing_keys(settings)
        if missing:
            return {"status": "error", "message": missing}
        self._start(settings)
        return {"status": "ok", "message": "Watcher restarted."}

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
        return [
            "--api-url",
            DEFAULT_API_URL,
            "--gluetun-url",
            self._gluetun_url(settings),
            "--journal",
            str(JOURNAL_PATH),
        ]

    def _start(self, settings: dict) -> None:
        process.terminate_strays()
        token = uuid.uuid4().hex
        pid = process.spawn(
            BASE_DIR,
            self._arguments(settings),
            token,
            LOG_PATH,
            extra_env={
                API_KEY_ENV: _as_text(settings.get("api_key"), ""),
                GLUETUN_KEY_ENV: _as_text(settings.get("gluetun_api_key"), ""),
            },
        )
        self._remember({"pid": pid, "token": token, "started_at": time.time()})
        if not self._settled(pid, token):
            process.terminate(pid)
            self._remember({}, clear=["pid", "token"])
            raise RuntimeError(f"The watcher exited on startup. See {LOG_PATH}.")

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

    def _heartbeat_due(self) -> bool:
        global _heartbeat_checked_at
        now = time.monotonic()
        with _heartbeat_lock:
            if now - _heartbeat_checked_at < HEARTBEAT_INTERVAL_SECONDS:
                return False
            _heartbeat_checked_at = now
        return True

    def _state(self) -> dict:
        return state_module.load(STATE_PATH)

    def _remember(self, updates: dict, clear: list[str] | None = None) -> dict:
        return state_module.remember(STATE_PATH, updates, clear or [])
