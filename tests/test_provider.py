from __future__ import annotations

import urllib.parse

import pytest

from gluetun_rotate import provider
from gluetun_rotate.provider import Account, Dispatcharr, Probe, probe
from gluetun_rotate.web import ApiError, Response

ACCOUNT = Account(
    name="Miglior IPTV",
    server_url="http://provider.example/",
    username="user",
    password="p@ss word",
    user_agent="TiviMate/5.1.6 (Android 12)",
)


def test_the_probe_asks_the_account_endpoint_with_encoded_credentials():
    parsed = urllib.parse.urlsplit(ACCOUNT.probe_url())
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "http://provider.example/player_api.php"
    )
    assert urllib.parse.parse_qs(parsed.query) == {"username": ["user"], "password": ["p@ss word"]}


@pytest.mark.parametrize("status", [520, 521, 522, 523, 524, 525, 526, 527])
def test_cloudflare_origin_errors_count_as_a_refused_address(status):
    assert Probe(account="x", status=status).refused is True


@pytest.mark.parametrize("status", [200, 403, 404, 502, 503, 507, 509, None])
def test_everything_else_is_not_a_refused_address(status):
    assert Probe(account="x", status=status).refused is False


def test_the_probe_sends_the_account_user_agent(monkeypatch):
    seen = {}

    def fake_fetch(url, headers=None, timeout=0.0, **_):
        seen.update(headers or {})
        return Response(status=520, body=b"")

    monkeypatch.setattr(provider, "fetch", fake_fetch)
    result = probe(ACCOUNT)
    assert result == Probe(account="Miglior IPTV", status=520)
    assert seen["User-Agent"] == "TiviMate/5.1.6 (Android 12)"


def test_a_probe_without_an_answer_is_reported_without_the_credentials(monkeypatch):
    def fake_fetch(url, headers=None, timeout=0.0, **_):
        raise ApiError("GET failed: timed out")

    monkeypatch.setattr(provider, "fetch", fake_fetch)
    result = probe(ACCOUNT)
    assert result.status is None
    assert result.refused is False
    assert "p@ss" not in result.describe()
    assert "user" not in result.describe().replace("Miglior IPTV", "")


ROUTES = {
    "/api/m3u/accounts/": [
        {"id": 1, "name": "custom", "account_type": "STD", "is_active": True},
        {"id": 3, "name": "Dummy", "account_type": "XC", "is_active": True, "server_url": ""},
        {
            "id": 2,
            "name": "Miglior IPTV",
            "account_type": "XC",
            "is_active": True,
            "server_url": "http://provider.example/",
            "username": "user",
            "password": "pass",
            "user_agent": None,
        },
        {
            "id": 4,
            "name": "Backup",
            "account_type": "XC",
            "is_active": True,
            "server_url": "http://backup.example",
            "username": "u2",
            "password": "p2",
            "user_agent": 2,
        },
        {
            "id": 5,
            "name": "Old",
            "account_type": "XC",
            "is_active": False,
            "server_url": "http://old.example",
            "username": "u3",
            "password": "p3",
        },
    ],
    "/api/core/settings/": [
        {"key": "epg_settings", "value": {}},
        {"key": "stream_settings", "value": {"default_user_agent": 1}},
    ],
    "/api/core/useragents/1/": {"id": 1, "user_agent": "TiviMate/5.1.6 (Android 12)"},
    "/api/core/useragents/2/": {"id": 2, "user_agent": "VLC/3.0.21 LibVLC/3.0.21"},
}


def test_only_active_xtream_accounts_with_credentials_are_probed(monkeypatch):
    monkeypatch.setattr(provider, "request_json", lambda base, path, **_: ROUTES[path])
    accounts = Dispatcharr("http://127.0.0.1:9191", "key").accounts()
    assert [(a.name, a.user_agent) for a in accounts] == [
        ("Miglior IPTV", "TiviMate/5.1.6 (Android 12)"),
        ("Backup", "VLC/3.0.21 LibVLC/3.0.21"),
    ]
