from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from .constants import PROBE_TIMEOUT_SECONDS, REFUSED_STATUSES
from .forbidden import Streaming, feed_of
from .web import ApiError, fetch, request_json

XTREAM_CODES = "XC"


@dataclass(frozen=True)
class Account:
    name: str
    server_url: str
    username: str
    password: str
    user_agent: str

    def probe_url(self) -> str:
        query = urllib.parse.urlencode({"username": self.username, "password": self.password})
        return f"{self.server_url.rstrip('/')}/player_api.php?{query}"


@dataclass(frozen=True)
class Probe:
    account: str
    status: int | None
    detail: str = ""

    @property
    def refused(self) -> bool:
        return self.status in REFUSED_STATUSES

    def describe(self) -> str:
        if self.status is None:
            return f"{self.account}: no answer ({self.detail})"
        return f"{self.account}: HTTP {self.status}"


def probe(account: Account, timeout: float = PROBE_TIMEOUT_SECONDS) -> Probe:
    headers = {"User-Agent": account.user_agent} if account.user_agent else {}
    try:
        response = fetch(account.probe_url(), headers=headers, timeout=timeout)
    except ApiError as error:
        return Probe(account=account.name, status=None, detail=str(error))
    return Probe(account=account.name, status=response.status)


def _rows(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _as_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


class Dispatcharr:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def accounts(self) -> list[Account]:
        rows = [row for row in _rows(self._get("/api/m3u/accounts/")) if _usable(row)]
        default_agent: str | None = None
        found: list[Account] = []
        for row in rows:
            agent_id = _as_int(row.get("user_agent"))
            if agent_id:
                agent = self._user_agent(agent_id)
            else:
                if default_agent is None:
                    default_agent = self._default_user_agent()
                agent = default_agent
            found.append(
                Account(
                    name=str(row.get("name") or row.get("id")),
                    server_url=str(row["server_url"]),
                    username=str(row["username"]),
                    password=str(row["password"]),
                    user_agent=agent,
                )
            )
        return found

    def streaming(self) -> list[Streaming]:
        payload = self._get("/proxy/ts/status")
        rows = payload.get("channels", []) if isinstance(payload, dict) else []
        return [
            Streaming(
                channel=str(row.get("channel_id") or ""),
                name=str(row.get("channel_name") or ""),
                feed=feed_of(str(row.get("url") or "")),
            )
            for row in rows
            if isinstance(row, dict)
        ]

    def _default_user_agent(self) -> str:
        for row in _rows(self._get("/api/core/settings/")):
            value = row.get("value")
            if row.get("key") == "stream_settings" and isinstance(value, dict):
                agent_id = _as_int(value.get("default_user_agent"))
                return self._user_agent(agent_id) if agent_id else ""
        return ""

    def _user_agent(self, agent_id: int) -> str:
        payload = self._get(f"/api/core/useragents/{agent_id}/")
        return str(payload.get("user_agent") or "") if isinstance(payload, dict) else ""

    def _get(self, path: str) -> object:
        return request_json(self.base_url, path, headers={"X-API-Key": self.api_key})


def _usable(row: dict) -> bool:
    return (
        row.get("account_type") == XTREAM_CODES
        and bool(row.get("is_active"))
        and all(row.get(key) for key in ("server_url", "username", "password"))
    )
