"""Configure a Library Folder without leaving the Library."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.gui.settings_dialog import kind_label


class LibraryFolderDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(self.tr("Add Library Folder"))
        layout = QFormLayout(self)
        name = QLabel(str(path))
        name.setWordWrap(True)
        layout.addRow(self.tr("Folder"), name)
        self.kind = QComboBox()
        for kind in ContentKind:
            self.kind.addItem(kind_label(kind), kind)
        self.kind.setCurrentIndex(self.kind.findData(LibraryFolder(path).kind))
        layout.addRow(self.tr("Content Kind"), self.kind)
        self.scan_depth = QSpinBox()
        self.scan_depth.setRange(1, 5)
        self.scan_depth.setValue(1)
        layout.addRow(self.tr("Scan depth"), self.scan_depth)
        hint = QLabel(
            self.tr("Depth 1 treats each file or folder directly inside as one Local Item.")
        )
        hint.setWordWrap(True)
        layout.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def folder(self) -> LibraryFolder:
        return LibraryFolder(
            self.path, self.scan_depth.value(), ContentKind(self.kind.currentData())
        )
