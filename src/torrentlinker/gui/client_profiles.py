"""Profile list and the existing connection/folder editor."""

from __future__ import annotations

import copy

from keyring.errors import KeyringError
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.client_profiles import pending_work
from torrentlinker.config import Settings
from torrentlinker.credentials import set_secret
from torrentlinker.gui.settings_dialog import SettingsDialog
from torrentlinker.store import Store


class ClientProfilesDialog(QDialog):
    def __init__(self, settings: Settings, store: Store, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings · Torrent clients"))
        self.resize(660, 420)
        self.original = settings
        self.settings = copy.deepcopy(settings)
        self.settings.capture_client()
        self.store = store
        self.secret_values: dict[str, str] = {}
        layout = QVBoxLayout(self)
        self.clients = QListWidget()
        self.clients.itemDoubleClicked.connect(lambda _: self.edit())
        layout.addWidget(self.clients)
        row = QHBoxLayout()
        for label, callback in [
            (self.tr("Add client"), self.add),
            (self.tr("Edit settings"), self.edit),
            (self.tr("Make default"), self.make_default),
            (self.tr("Remove client"), self.remove),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        self.clients.clear()
        for profile in self.settings.client_profiles:
            suffix = self.tr(" · Default") if profile.id == self.settings.default_client_id else ""
            self.clients.addItem(f"{profile.name} · {profile.client.display_name}{suffix}")
        ids = [p.id for p in self.settings.client_profiles]
        self.clients.setCurrentRow(ids.index(self.settings.active_client_id))

    def selected(self):
        row = self.clients.currentRow()
        return self.settings.client_profiles[row] if row >= 0 else self.settings.profile()

    def add(self):
        name, accepted = QInputDialog.getText(self, self.tr("Add client"), self.tr("Client name"))
        if not accepted or not name.strip():
            return
        profile = self.settings.add_client(name)
        self.settings.select_client(profile.id)
        self.refresh()
        self.edit()

    def edit(self):
        active = self.settings.active_client_id
        working = self.settings.for_client(self.selected().id)
        if SettingsDialog(working, self, secret_values=self.secret_values).exec():
            working.capture_client()
            working.select_client(active)
            self.settings = working
            self.refresh()

    def make_default(self):
        self.settings.default_client_id = self.selected().id
        self.refresh()

    def remove(self):
        profile = self.selected()
        if len(self.settings.client_profiles) == 1 or pending_work(
            self.settings, self.store, profile.id
        ):
            QMessageBox.warning(
                self,
                self.tr("Client in use"),
                self.tr(
                    "Keep at least one client. Finish or remove its pending downloads, Plan and "
                    "Verifications before removing it."
                ),
            )
            return
        self.settings.capture_client()
        remaining = [p for p in self.settings.client_profiles if p.id != profile.id]
        self.settings.select_client(remaining[0].id)
        self.settings.client_profiles = remaining
        if self.settings.default_client_id == profile.id:
            self.settings.default_client_id = remaining[0].id
        self.refresh()

    def save(self):
        try:
            for name, value in self.secret_values.items():
                set_secret(name, value)
        except KeyringError as error:
            QMessageBox.warning(
                self,
                QCoreApplication.translate("SettingsDialog", "Keyring unavailable"),
                QCoreApplication.translate(
                    "SettingsDialog", "Your keys could not be saved in the system keyring: {0}"
                ).format(error),
            )
            return
        self.settings.capture_client()
        self.original.__dict__.update(copy.deepcopy(self.settings.__dict__))
        self.accept()
