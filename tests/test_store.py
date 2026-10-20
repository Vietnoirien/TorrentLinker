from pathlib import Path

from torrentlinker.store import Store


def test_edited_query_is_remembered_per_local_item(tmp_path: Path) -> None:
    item = Path("/windocs/E-Book/Le joueur d'echecs - Stefan Zweig.epub")
    Store(tmp_path / "s.db").set_item_query(item, "joueur echecs zweig")

    reopened = Store(tmp_path / "s.db")

    assert reopened.item_query(item) == "joueur echecs zweig"
    assert reopened.item_query(Path("/other")) is None
