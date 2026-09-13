from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass

from .constants import API_TIMEOUT_SECONDS, USER_AGENT

ERROR_BODY_CHARS = 200


class ApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


def fetch(
    url: str,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: Mapping[str, object] | None = None,
    timeout: float = API_TIMEOUT_SECONDS,
) -> Response:
    sent = {"Accept": "application/json", "User-Agent": USER_AGENT, **dict(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        sent["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=sent)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(status=int(response.status), body=response.read())
    except urllib.error.HTTPError as error:
        return Response(status=int(error.code), body=error.read()[:ERROR_BODY_CHARS])
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise ApiError(f"{method} failed: {reason}") from error


def request_json(
    base_url: str,
    path: str,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: Mapping[str, object] | None = None,
) -> object:
    try:
        response = fetch(f"{base_url.rstrip('/')}{path}", method, headers, body)
    except ApiError as error:
        raise ApiError(f"{method} {path} failed: {error}") from error
    if not 200 <= response.status < 300:
        detail = response.body.decode("utf-8", "ignore").strip()
        raise ApiError(f"{method} {path} returned {response.status} {detail}".strip())
    if not response.body:
        return {}
    try:
        return json.loads(response.body)
    except ValueError as error:
        raise ApiError(f"{method} {path} returned invalid JSON") from error
