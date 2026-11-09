from __future__ import annotations

from gluetun_rotate import state


def _old_runtime(folder):
    state.save(folder / "state.json", {"applied": True})
    (folder / "media").mkdir()
    (folder / "media" / "card.png").write_bytes(b"png")
    return folder


def test_migrate_moves_an_old_folder_into_a_missing_one(tmp_path):
    old = _old_runtime(tmp_path / "plugin" / ".runtime")
    target = tmp_path / "_data" / "slug"
    assert state.migrate([old], target) is True
    assert state.load(target / "state.json") == {"applied": True}
    assert (target / "media" / "card.png").read_bytes() == b"png"
    assert not old.exists()


def test_migrate_fills_an_empty_folder_dispatcharr_created(tmp_path):
    old = _old_runtime(tmp_path / "plugin" / ".runtime")
    target = tmp_path / "_data" / "slug"
    target.mkdir(parents=True)
    assert state.migrate([old], target) is True
    assert state.load(target / "state.json") == {"applied": True}


def test_migrate_leaves_a_folder_that_already_holds_state_alone(tmp_path):
    old = _old_runtime(tmp_path / "plugin" / ".runtime")
    target = tmp_path / "_data" / "slug"
    state.save(target / "state.json", {"pid": 7})
    assert state.migrate([old], target) is False
    assert state.load(target / "state.json") == {"pid": 7}
    assert state.load(old / "state.json") == {"applied": True}


def test_migrate_without_anything_to_move_creates_nothing(tmp_path):
    target = tmp_path / "_data" / "slug"
    assert state.migrate([tmp_path / "plugin" / ".runtime"], target) is False
    assert not (tmp_path / "_data").exists()


def test_migrate_takes_the_first_source_that_holds_something(tmp_path):
    first = tmp_path / "_data" / "gluetun-rotate"
    state.save(first / "state.json", {"from": "first"})
    second = _old_runtime(tmp_path / "plugin" / ".runtime")
    target = tmp_path / "_data" / "gluetun_rotate"
    assert state.migrate([target, first, second], target) is True
    assert state.load(target / "state.json") == {"from": "first"}
    assert second.exists()
