from __future__ import annotations

from pathlib import Path

from gluetun_rotate.tailer import Tailer


def test_only_lines_written_after_it_opened_are_returned(tmp_path: Path):
    path = tmp_path / "dispatcharr.log"
    path.write_text("old\n", encoding="utf-8")
    tailer = Tailer(path)
    assert list(tailer.read()) == []
    with path.open("a", encoding="utf-8") as handle:
        handle.write("new\n")
    assert list(tailer.read()) == ["new"]


def test_a_half_written_line_is_held_until_it_ends(tmp_path: Path):
    path = tmp_path / "dispatcharr.log"
    path.write_text("", encoding="utf-8")
    tailer = Tailer(path)
    list(tailer.read())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("cushion=0s")
    assert list(tailer.read()) == []
    with path.open("a", encoding="utf-8") as handle:
        handle.write("(pcr)\n")
    assert list(tailer.read()) == ["cushion=0s(pcr)"]


def test_a_truncated_file_is_read_again_from_its_start(tmp_path: Path):
    path = tmp_path / "dispatcharr.log"
    path.write_text("first line that is long\n", encoding="utf-8")
    tailer = Tailer(path)
    list(tailer.read())
    path.write_text("short\n", encoding="utf-8")
    assert list(tailer.read()) == ["short"]


def test_a_file_replaced_underneath_is_read_from_its_start(tmp_path: Path):
    path = tmp_path / "dispatcharr.log"
    path.write_text("first\n", encoding="utf-8")
    tailer = Tailer(path)
    list(tailer.read())
    path.unlink()
    path.write_text("after rotation\nand more\n", encoding="utf-8")
    assert list(tailer.read()) == ["after rotation", "and more"]


def test_a_missing_file_is_not_an_error(tmp_path: Path):
    assert list(Tailer(tmp_path / "absent.log").read()) == []


def test_reading_from_the_start_returns_what_is_already_there(tmp_path: Path):
    path = tmp_path / "dispatcharr.log"
    path.write_text("one\ntwo\n", encoding="utf-8")
    assert list(Tailer(path, from_start=True).read()) == ["one", "two"]


def test_nothing_is_returned_twice(tmp_path: Path):
    path = tmp_path / "dispatcharr.log"
    path.write_text("", encoding="utf-8")
    tailer = Tailer(path)
    list(tailer.read())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("one\ntwo\n")
    assert list(tailer.read()) == ["one", "two"]
    assert list(tailer.read()) == []
