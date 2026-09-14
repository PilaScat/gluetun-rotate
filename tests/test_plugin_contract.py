from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "_dispatcharr_plugin_gluetun_rotate"

ALLOWED_FIELD_TYPES = {"boolean", "number", "string", "text", "select", "info"}
PLUGIN_HOOK_EVENTS = {
    "channel_start",
    "channel_stop",
    "channel_reconnect",
    "channel_error",
    "channel_failover",
    "stream_switch",
    "recording_start",
    "recording_end",
    "epg_refresh",
    "epg_error",
    "m3u_refresh",
    "m3u_error",
    "client_connect",
    "client_disconnect",
    "login_failed",
    "epg_blocked",
    "m3u_blocked",
    "vod_start",
    "vod_stop",
}


@pytest.fixture(scope="module")
def manifest() -> dict:
    with (ROOT / "plugin.json").open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def loaded_module():
    namespace = types.ModuleType(PACKAGE_NAME)
    namespace.__path__ = [str(ROOT)]  # type: ignore[attr-defined]
    namespace.__package__ = PACKAGE_NAME
    sys.modules[PACKAGE_NAME] = namespace

    module_name = f"{PACKAGE_NAME}.plugin"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    yield module

    for name in list(sys.modules):
        if name == PACKAGE_NAME or name.startswith(f"{PACKAGE_NAME}."):
            del sys.modules[name]


@pytest.fixture
def isolated_runtime(loaded_module, tmp_path, monkeypatch):
    runtime = tmp_path / ".runtime"
    for name in ("STATE_PATH", "JOURNAL_PATH", "LOG_PATH", "MEDIA_CACHE_DIR"):
        if hasattr(loaded_module, name):
            monkeypatch.setattr(loaded_module, name, runtime / getattr(loaded_module, name).name)
    monkeypatch.setattr(loaded_module, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(loaded_module.process, "terminate_strays", lambda *_a, **_k: [])
    if hasattr(loaded_module.process, "find_servers"):
        monkeypatch.setattr(loaded_module.process, "find_servers", lambda *_a, **_k: [])
    return runtime


def test_the_loader_import_path_finds_a_plugin_class(loaded_module):
    assert hasattr(loaded_module, "Plugin")


def test_importing_the_plugin_does_not_need_django(loaded_module):
    assert "django" not in sys.modules
    assert not any(name.startswith("apps.") for name in sys.modules)


def test_the_instance_reports_the_manifest_metadata(loaded_module, manifest):
    plugin = loaded_module.Plugin()
    assert plugin.name == manifest["name"]
    assert plugin.version == manifest["version"]
    assert plugin.description == manifest["description"]
    assert plugin.author == manifest["author"]
    assert plugin.fields == manifest["fields"]
    assert plugin.actions == manifest["actions"]


def test_every_manifest_action_has_a_handler(loaded_module, manifest, isolated_runtime):
    plugin = loaded_module.Plugin()
    for action in manifest["actions"]:
        result = plugin.run(action["id"], {}, {"settings": {}})
        assert not str(result.get("message", "")).startswith("Unknown action")


def test_an_unknown_action_is_refused(loaded_module, isolated_runtime):
    result = loaded_module.Plugin().run("nope", {}, {"settings": {}})
    assert result["status"] == "error"
    assert "Unknown action" in result["message"]


def test_manifest_fields_use_only_types_dispatcharr_can_render(manifest):
    for field in manifest["fields"]:
        assert field["type"] in ALLOWED_FIELD_TYPES, field["id"]


def test_manifest_field_ids_are_unique(manifest):
    ids = [field["id"] for field in manifest["fields"]]
    assert len(ids) == len(set(ids))


def test_the_action_buttons_look_like_one_set(manifest):
    actions = manifest["actions"]
    variants = [action.get("button_variant") for action in actions]
    assert variants.count("filled") == 1
    assert set(variants) <= {"filled", "default"}
    assert all(action.get("button_label") for action in actions)
    assert max(len(a["button_label"]) for a in actions) <= 8


def test_the_destructive_action_is_last_coloured_and_confirmed(manifest):
    last = manifest["actions"][-1]
    assert last["id"] == "remove"
    assert last["button_color"] == "red"
    assert last["confirm"]["required"] is True
    assert [a for a in manifest["actions"] if a.get("button_color")] == [last]


def test_action_labels_and_descriptions_stay_short_and_parallel(manifest):
    for action in manifest["actions"]:
        assert len(action["label"].split()) <= 3, action["id"]
        description = action["description"]
        assert description.endswith("."), action["id"]
        assert description.count(".") == 1, action["id"]
        assert len(description.split()) <= 13, action["id"]


def test_manifest_binds_only_events_that_reach_plugin_hooks(manifest):
    for action in manifest["actions"]:
        for event in action.get("events", []):
            assert event in PLUGIN_HOOK_EVENTS, event


def test_manifest_carries_what_the_registry_requires(manifest):
    for key in ("name", "version", "description", "author", "license"):
        assert manifest.get(key), key
    assert manifest["license"] == "MIT"
    assert manifest["source_type"] == "external"
    assert "{version}" in manifest["source_url"]


def test_manifest_version_matches_the_package_constant(manifest):
    from gluetun_rotate.constants import PLUGIN_VERSION

    assert manifest["version"] == PLUGIN_VERSION


def test_runtime_state_is_not_kept_in_the_plugin_settings():
    source = (ROOT / "plugin.py").read_text(encoding="utf-8")
    assert "PluginConfig" not in source
    assert "STATE_PATH" in source


def test_the_state_file_lives_beside_the_plugin(loaded_module):
    assert loaded_module.STATE_PATH.parent == loaded_module.RUNTIME_DIR
    assert loaded_module.RUNTIME_DIR.parent == ROOT


def test_applying_without_the_dispatcharr_key_says_so(loaded_module, isolated_runtime):
    result = loaded_module.Plugin().run("apply", {}, {"settings": {"gluetun_api_key": "g"}})
    assert result["status"] == "error"
    assert "Dispatcharr API key" in result["message"]


def test_applying_without_the_gluetun_key_says_so(loaded_module, isolated_runtime):
    result = loaded_module.Plugin().run("apply", {}, {"settings": {"api_key": "k"}})
    assert result["status"] == "error"
    assert "Gluetun" in result["message"]


def test_settings_read_by_the_code_are_declared_in_the_manifest(manifest):
    declared = {field["id"] for field in manifest["fields"]}
    assert {"api_key", "gluetun_api_key", "gluetun_url"} <= declared


def test_the_keys_reach_the_watcher_through_its_environment_not_its_command_line(
    loaded_module,
):
    settings = {"api_key": "dispatcharr-secret", "gluetun_api_key": "gluetun-secret"}
    arguments = loaded_module.Plugin()._arguments(settings)
    assert "dispatcharr-secret" not in arguments
    assert "gluetun-secret" not in arguments
    assert arguments[arguments.index("--gluetun-url") + 1] == "http://127.0.0.1:8000"
