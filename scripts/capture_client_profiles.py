"""Capture the client and Plan dialogs with offline sample profiles, in both languages."""

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from torrentlinker import i18n
from torrentlinker.config import Settings
from torrentlinker.domain import TorrentClient
from torrentlinker.gui.client_profiles import ClientProfilesDialog
from torrentlinker.gui.plan_clients import PlanClientsDialog
from torrentlinker.gui.theme import apply_theme
from torrentlinker.store import Store

app = QApplication([])
app.setApplicationName("TorrentLinker documentation")
apply_theme(app, "dark")
with TemporaryDirectory(prefix="tl-client-docs-") as temporary, ExitStack() as stack:
    stack.enter_context(patch("keyring.get_password", return_value=None))
    settings = Settings()
    settings.profile().name = "NAS"
    seedbox = settings.add_client("Seedbox", TorrentClient.DELUGE)
    settings.add_client("Transmission", TorrentClient.TRANSMISSION)
    store = Store(Path(temporary) / "state.db")
    for language in ("en", "fr"):
        translators = i18n.install(app, language)
        output = Path("docs/guide/images") / ("en" if language == "en" else "")
        for dialog, name in [
            (ClientProfilesDialog(settings, store), "clients"),
            (
                PlanClientsDialog(settings, {"default": 20 * 1024**3, seedbox.id: 50 * 1024**3}),
                "plan-clients",
            ),
        ]:
            dialog.show()
            QTest.qWait(50)
            assert dialog.grab().save(str(output / (name + ".png")))
            dialog.close()
        for translator in translators:
            app.removeTranslator(translator)
