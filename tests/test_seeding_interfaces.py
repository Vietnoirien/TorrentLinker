"""Shared Seeding owner workflow; introduced before its renderer replacement."""

from pathlib import Path

from PySide6.QtCore import QSettings

from tests.test_community_interfaces import js, wait_js
from torrentlinker.domain import Torrent
from torrentlinker.downloads import IndexerCategory
from torrentlinker.gui.zen_view import SeedingView
from torrentlinker.seeding import Seeding, SeedingRow
from torrentlinker.zen import ZenDay


def test_shared_seeding_sort_filter_and_expansion_survive_reopening(qtbot, tmp_path):
    data = Seeding(
        [
            SeedingRow(Torrent("a", "Small", Path("/data"), size=9000), 0.1, 7010),
            SeedingRow(Torrent("b", "Large", Path("/data"), size=1000000), 0.2, 7010),
            SeedingRow(Torrent("c", "Broad", Path("/data"), size=100), 0.3, 7000),
        ],
        ZenDay([0.1, 0.2, 0.3]),
        [],
        {7000: IndexerCategory("Books"), 7010: IndexerCategory("Comics", 7000)},
    )
    settings = QSettings(str(tmp_path / "owner.ini"), QSettings.Format.IniFormat)
    view = SeedingView(lambda: lambda: data, preferences=settings)
    qtbot.addWidget(view)
    view.show_seeding(data)
    view.resize(1200, 800)
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('.seeding-group').length===2")
    js(qtbot, view, "document.querySelector('#seeding-expand').click()")
    wait_js(qtbot, view, "document.querySelectorAll('tbody tr').length===3")
    js(
        qtbot,
        view,
        "document.querySelector('#seeding-sort').value='name';document.que"
        "rySelector('#seeding-sort').dispatchEvent(new Event('change'))",
    )
    wait_js(
        qtbot,
        view,
        "document.querySelector('[data-group=\"7000/7010\"] tbody tr').textC"
        "ontent.includes('Small')",
    )
    view.close()
    reopened = SeedingView(lambda: lambda: data, preferences=settings)
    qtbot.addWidget(reopened)
    reopened.show_seeding(data)
    reopened.show()
    wait_js(qtbot, reopened, "document.querySelectorAll('.seeding-group[open]').length===2")
    js(
        qtbot,
        reopened,
        "document.querySelector('#seeding-query').value='Large';document.q"
        "uerySelector('#seeding-query').dispatchEvent(new Event('input',{b"
        "ubbles:true}))",
    )
    wait_js(qtbot, reopened, "document.querySelectorAll('tbody tr').length===1")
    assert js(qtbot, reopened, "document.querySelector('tbody').textContent.includes('Large')")
