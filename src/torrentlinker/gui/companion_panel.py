"""Browser companion controls: connection, extension file and session downloads."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from torrentlinker.gui.controls import set_role


class CompanionPanel(QGroupBox):
    pair_requested = Signal()
    disconnect_requested = Signal()
    extension_requested = Signal()
    session_downloads_toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("Browser companion"), parent)
        layout = QVBoxLayout(self)
        self.status = self._label()
        layout.addWidget(self.status)
        layout.addWidget(
            self._label(
                self.tr(
                    "Connect once to sync account statistics, transfers, seed time and active "
                    "seeds every two minutes. Your login stays in the browser. "
                    "Keep a signed-in c411 tab open."
                )
            )
        )
        actions = QHBoxLayout()
        self.extension_button = QPushButton(self.tr("Save extension…"))
        self.extension_button.clicked.connect(self.extension_requested)
        self.pair_button = QPushButton(self.tr("Connect companion"))
        set_role(self.pair_button, "primary")
        self.pair_button.clicked.connect(self.pair_requested)
        self.disconnect_button = QPushButton(self.tr("Disconnect & clear").replace("&", "&&"))
        self.disconnect_button.clicked.connect(self.disconnect_requested)
        for button in (self.extension_button, self.pair_button, self.disconnect_button):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.pairing_box = QGroupBox(self.tr("Pair with this account"))
        pairing = QVBoxLayout(self.pairing_box)
        pairing.addWidget(
            self._label(
                self.tr(
                    "Connecting in your browser. Once the companion is installed, connection and "
                    "updates are automatic. Keep the browser connection page open during "
                    "installation."
                )
            )
        )
        self.pairing_box.hide()
        layout.addWidget(self.pairing_box)
        self.session_downloads = QCheckBox(self.tr("Download .torrent files with my c411 session"))
        self.session_downloads.setToolTip(
            self.tr(
                "Uses the signed-in browser tab instead of the API key. TorrentLinker adds no "
                "download cap of its own and stops at the first refusal from c411."
            )
        )
        self.session_downloads.toggled.connect(self._toggled)
        layout.addWidget(self.session_downloads)
        self.session_note = self._label(
            self.tr(
                "Only while this is on and the companion is connected. If c411 refuses the "
                "session, downloads stop; they never fall back to the API key."
            )
        )
        layout.addWidget(self.session_note)

    def _label(self, text: str = "") -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def _toggled(self, checked: bool) -> None:
        if not self._syncing:
            self.session_downloads_toggled.emit(checked)

    _syncing = False

    def show_pairing(self) -> None:
        self.pairing_box.show()

    def show_state(self, state: dict[str, Any]) -> None:
        paired = bool(state.get("paired"))
        api = state.get("api") or {}
        self.pair_button.setEnabled(bool(api.get("account_id")) and not state.get("error"))
        self.pair_button.setText(
            self.tr("Connect another browser") if paired else self.tr("Connect companion")
        )
        self.disconnect_button.setEnabled(
            bool(state.get("companion") or paired or self.pairing_box.isVisible())
        )
        if paired:
            self.pairing_box.hide()
        downloads = state.get("downloads") or {}
        self._syncing = True
        try:
            self.session_downloads.setEnabled(paired)
            self.session_downloads.setChecked(paired and bool(downloads.get("enabled")))
        finally:
            self._syncing = False
        if not paired:
            self.status.setText(self.tr("Not connected."))
        elif downloads.get("blocked"):
            self.status.setText(
                self.tr("c411 refused the session. Check the account and reconnect.")
            )
        elif downloads.get("retry_after"):
            self.status.setText(
                self.tr("c411 asked us to wait {0} s.").format(downloads["retry_after"])
            )
        elif downloads.get("available"):
            self.status.setText(self.tr("Connected. The browser tab is ready."))
        else:
            self.status.setText(self.tr("Connected. Keep a signed-in c411 tab open."))
