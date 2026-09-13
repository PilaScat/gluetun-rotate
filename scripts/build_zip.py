from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = "gluetun-rotate"
PACKAGE = "gluetun_rotate"
EXTRA_FILES = ("plugin.json", "plugin.py", "README.md", "LICENSE")
OPTIONAL_FILES = ("logo.png",)


def version() -> str:
    with (ROOT / "plugin.json").open(encoding="utf-8") as handle:
        return str(json.load(handle)["version"])


def sources() -> list[Path]:
    collected = [ROOT / name for name in EXTRA_FILES]
    collected += [
        path
        for path in sorted((ROOT / PACKAGE).rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    collected += [ROOT / name for name in OPTIONAL_FILES if (ROOT / name).is_file()]
    return collected


def build() -> Path:
    missing = [path for path in sources() if not path.is_file()]
    if missing:
        names = ", ".join(str(path.relative_to(ROOT)) for path in missing)
        raise SystemExit(f"Missing files: {names}")

    target = ROOT / "dist" / f"{FOLDER}-{version()}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sources():
            archive.write(path, f"{FOLDER}/{path.relative_to(ROOT).as_posix()}")
    return target


if __name__ == "__main__":
    built = build()
    print(f"{built.relative_to(ROOT)} ({built.stat().st_size} bytes)", file=sys.stdout)
