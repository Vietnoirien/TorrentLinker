from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.config import Settings
from torrentlinker.credentials import get_secret, set_secret
from torrentlinker.domain import LibraryFolder
from torrentlinker.gui.tasks import run_in_background
from torrentlinker.qbit import QbitApi

QBIT_PASSWORD = "qbit-password"


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))
        self.resize(720, 480)
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.addWidget(self._qbit_box())
        layout.addWidget(self._folders_box())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # qBittorrent -----------------------------------------------------------

    def _qbit_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("qBittorrent"))
        form = QFormLayout(box)
        self.qbit_host = QLineEdit(self.settings.qbit.host)
        self.qbit_user = QLineEdit(self.settings.qbit.username)
        self.qbit_password = QLineEdit(get_secret(QBIT_PASSWORD))
        self.qbit_password.setEchoMode(QLineEdit.EchoMode.Password)
        test = QPushButton(self.tr("Test connection"))
        test.clicked.connect(self._test_qbit)
        form.addRow(self.tr("WebUI address"), self.qbit_host)
        form.addRow(self.tr("Username"), self.qbit_user)
        form.addRow(self.tr("Password"), self.qbit_password)
        form.addRow("", test)
        return box

    def _test_qbit(self) -> None:
        api = QbitApi(self.qbit_host.text(), self.qbit_user.text(), self.qbit_password.text())
        run_in_background(
            api.check,
            lambda v: QMessageBox.information(
                self, self.tr("qBittorrent"), self.tr("Connected to qBittorrent {0}").format(v)
            ),
            lambda e: QMessageBox.warning(self, self.tr("qBittorrent"), str(e)),
        )

    # Library Folders -------------------------------------------------------

    def _folders_box(self) -> QGroupBox:
        box = QGroupBox(self.tr("Library Folders"))
        layout = QVBoxLayout(box)
        self.folders = QTableWidget(0, 2)
        self.folders.setHorizontalHeaderLabels([self.tr("Folder"), self.tr("Scan depth")])
        self.folders.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for f in self.settings.library_folders:
            self._add_folder_row(f)
        layout.addWidget(self.folders)

        row = QHBoxLayout()
        add = QPushButton(self.tr("Add folder…"))
        add.clicked.connect(self._pick_folder)
        remove = QPushButton(self.tr("Remove"))
        remove.clicked.connect(lambda: self.folders.removeRow(self.folders.currentRow()))
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)
        return box

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr("Choose a Library Folder"))
        if path:
            self._add_folder_row(LibraryFolder(Path(path)))

    def _add_folder_row(self, folder: LibraryFolder) -> None:
        r = self.folders.rowCount()
        self.folders.insertRow(r)
        self.folders.setItem(r, 0, QTableWidgetItem(str(folder.path)))
        depth = QSpinBox()
        depth.setRange(1, 5)
        depth.setValue(folder.depth)
        self.folders.setCellWidget(r, 1, depth)

    def _read_folders(self) -> list[LibraryFolder]:
        result = []
        for r in range(self.folders.rowCount()):
            cell = self.folders.item(r, 0)
            assert cell is not None
            path = Path(cell.text())
            depth = self.folders.cellWidget(r, 1)
            assert isinstance(depth, QSpinBox)
            existing = next((f for f in self.settings.library_folders if f.path == path), None)
            base = existing or LibraryFolder(path)
            result.append(LibraryFolder(path, depth.value(), base.kind, base.mapping))
        return result

    def _save(self) -> None:
        self.settings.qbit.host = self.qbit_host.text().strip()
        self.settings.qbit.username = self.qbit_user.text().strip()
        set_secret(QBIT_PASSWORD, self.qbit_password.text())
        self.settings.library_folders = self._read_folders()
        self.accept()
