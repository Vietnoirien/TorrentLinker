"""Every static folder ships in the package: a folder left out of package-data is missing from
the image, and its page answers 404 (Fichiers did, once)."""

import tomllib
from pathlib import Path

STATIC = Path("src/torrentlinker/web/static")


def test_every_static_folder_is_in_package_data():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    shipped = set(data["tool"]["setuptools"]["package-data"]["torrentlinker"])
    folders = {p.relative_to(STATIC).as_posix() for p in STATIC.rglob("*") if p.is_dir()}
    missing = sorted(f for f in folders if f"web/static/{f}/*" not in shipped)
    assert not missing, missing
