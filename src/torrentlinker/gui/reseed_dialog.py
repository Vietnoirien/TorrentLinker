"""Review archive Matches before starting a Library Reseed batch."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.controls import set_role
from torrentlinker.gui.library_model import human_size
from torrentlinker.library import LibraryEntry
from torrentlinker.review import CheckedCandidate


class ReseedDialog(QDialog):
    def __init__(
        self,
        archives: list[tuple[LibraryEntry, CheckedCandidate]],
        ready: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Matches inside archives"))
        self.resize(760, 350)
        self.archive: tuple[LibraryEntry, CheckedCandidate] | None = None
        layout = QVBoxLayout(self)
        message = QLabel(
            self.tr(
                "These Full Matches need unpacking before they can seed. "
                "Choose an archive to review its destination and free space, "
                "or reseed the Matches that are already unpacked."
            )
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        self.items = QTreeWidget()
        self.items.setHeaderLabels(
            [self.tr("Local Item"), self.tr("Candidate"), self.tr("Unpacked size")]
        )
        self.items.setRootIsDecorated(False)
        for entry, checked in archives:
            assert checked.unpack is not None
            item = QTreeWidgetItem(
                [
                    entry.item.path.name,
                    checked.candidate.title,
                    human_size(checked.unpack.item.size),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, (entry, checked))
            item.setToolTip(0, str(entry.item.path))
            item.setToolTip(1, checked.candidate.title)
            self.items.addTopLevelItem(item)
        if first := self.items.topLevelItem(0):
            self.items.setCurrentItem(first)
        self.items.header().resizeSection(0, 260)
        self.items.header().resizeSection(1, 320)
        layout.addWidget(self.items)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.unpack_button = QPushButton(self.tr("Unpack and reseed selected…"))
        set_role(self.unpack_button, "secondary")
        self.unpack_button.clicked.connect(self._choose_archive)
        buttons.addButton(self.unpack_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.ready_button = QPushButton(self.tr("Reseed ready Matches ({0})").format(ready))
        set_role(self.ready_button, "primary")
        self.ready_button.setEnabled(ready > 0)
        self.ready_button.clicked.connect(self.accept)
        buttons.addButton(self.ready_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_archive(self) -> None:
        if item := self.items.currentItem():
            self.archive = item.data(0, Qt.ItemDataRole.UserRole)
            self.accept()
