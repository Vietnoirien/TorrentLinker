"""Re-encode the stored poster masters from PNG to WebP. Run it yourself:

    .venv/bin/python scripts/convert_artwork_masters.py --config DIR          # report only
    .venv/bin/python scripts/convert_artwork_masters.py --config DIR --apply  # convert

Posters arrive from the tracker as JPEGs of about 50 KB and were stored losslessly as PNG,
at roughly ten times that. New ones are written as WebP; this converts the ones already
stored and repoints the records at them.

Each master keeps its name: the key is the SHA-256 of the bytes as downloaded, so only the
suffix changes, and the derived `-grid`/`-hero` copies are named from the stem and stay
valid. The application reads either suffix, so stopping part way leaves everything working.

Nothing is deleted until its replacement is written and every reference to it is updated, in
one transaction per master. Run it with the application stopped: it rewrites rows the running
application also writes.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

MASTER = re.compile(r"^([a-f0-9]{64})\.png$")


def masters(folder: Path) -> list[Path]:
    """The PNG masters, which sit beside the `variants` folder, not inside it."""
    return sorted(path for path in folder.glob("*.png") if MASTER.match(path.name))


def references(db: sqlite3.Connection, key: str) -> int:
    """How many stored records name this master."""
    found = 0
    for table in ("media_items", "media_options"):
        for (body,) in db.execute(f"SELECT body FROM {table}"):  # noqa: S608 - fixed names
            found += (body or "").count(key)
    return found


def repoint(db: sqlite3.Connection, old: str, new: str) -> int:
    """Name `new` wherever a record named `old`. Returns the rows changed."""
    changed = 0
    for table, identity in (("media_items", ("client", "id")), ("media_options", ("key",))):
        columns = ", ".join(identity)
        rows = db.execute(
            f"SELECT {columns}, body FROM {table} WHERE body LIKE ?",  # noqa: S608 - fixed names
            (f"%{old}%",),
        ).fetchall()
        for row in rows:
            body = row[-1].replace(old, new)
            where = " AND ".join(f"{name}=?" for name in identity)
            db.execute(
                f"UPDATE {table} SET body=? WHERE {where}",  # noqa: S608 - fixed names
                (body, *row[:-1]),
            )
            changed += 1
    return changed


def convert(path: Path) -> Path:
    """Write the WebP beside the PNG, whole, and return it."""
    from PIL import Image

    target = path.with_suffix(".webp")
    partial = path.with_name(f".{uuid4().hex}.tmp")
    try:
        with Image.open(path) as picture:
            picture.load()
            picture.convert("RGB").save(partial, format="WEBP", quality=90, method=4)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="the configuration directory")
    parser.add_argument("--apply", action="store_true", help="convert; otherwise only report")
    args = parser.parse_args()

    folder = args.config / "media-artwork"
    database = args.config / "media.sqlite"
    if not folder.is_dir() or not database.is_file():
        print(f"No artwork store under {args.config}.")
        return 1

    found = masters(folder)
    before = sum(path.stat().st_size for path in found)
    print(f"{len(found)} PNG masters, {before / 1e6:.0f} MB")
    if not found:
        return 0
    if not args.apply:
        sample = convert(found[0])
        after = sample.stat().st_size
        sample.unlink()
        print(
            f"first one: {found[0].stat().st_size / 1024:.0f} KB -> {after / 1024:.0f} KB "
            f"({100 - after * 100 / found[0].stat().st_size:.0f}% smaller)"
        )
        remaining = before * after / found[0].stat().st_size
        print(
            f"about {remaining / 1e6:.1f} MB would remain, "
            f"{(before - remaining) / 1e6:.0f} MB reclaimed."
        )
        print("Re-run with --apply, with the application stopped.")
        return 0

    db = sqlite3.connect(database)
    converted = kept = 0
    saved = 0
    for path in found:
        key = path.name
        new = key.removesuffix(".png") + ".webp"
        try:
            target = convert(path)
        except Exception as error:  # noqa: BLE001 - one unreadable master stops nothing
            print(f"  {key[:12]}… left as it is: {type(error).__name__}")
            kept += 1
            continue
        with db:  # the rows and the file move together, or neither does
            repoint(db, key, new)
        saved += path.stat().st_size - target.stat().st_size
        path.unlink()
        converted += 1
    db.close()
    print(f"converted {converted}, left {kept}, reclaimed {saved / 1e6:.0f} MB")
    if kept:
        print("What was left still reads: the application accepts either suffix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
