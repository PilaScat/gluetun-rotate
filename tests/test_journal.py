from __future__ import annotations

from pathlib import Path

from gluetun_rotate.journal import Journal


def test_the_journal_keeps_what_was_written_in_order(tmp_path: Path):
    journal = Journal(tmp_path / "journal.jsonl", limit=10)
    journal.write("refused", account="Provider", status=520)
    journal.write("rotated", before="1.1.1.1", after="2.2.2.2")
    assert [row["event"] for row in journal.read()] == ["refused", "rotated"]


def test_the_journal_trims_itself_to_its_limit(tmp_path: Path):
    journal = Journal(tmp_path / "journal.jsonl", limit=3)
    for number in range(20):
        journal.write("refused", number=number)
    assert [row["number"] for row in journal.read()][-1] == 19
    assert len((tmp_path / "journal.jsonl").read_text().splitlines()) <= 12
