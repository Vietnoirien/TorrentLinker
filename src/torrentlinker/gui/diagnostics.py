"""Save a support report only to the location chosen by the user."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from torrentlinker.diagnostics import report_json


def export_report(parent: QWidget, report: Callable[[], dict]) -> None:
    filename, _ = QFileDialog.getSaveFileName(
        parent,
        QCoreApplication.translate("Diagnostics", "Export support report"),
        "torrentlinker-diagnostics.json",
        QCoreApplication.translate("Diagnostics", "JSON files (*.json)"),
    )
    if not filename:
        return
    try:
        Path(filename).write_text(report_json(report()), encoding="utf-8")
    except OSError:
        QMessageBox.warning(
            parent,
            QCoreApplication.translate("Diagnostics", "Support report"),
            QCoreApplication.translate(
                "Diagnostics",
                "The report could not be saved. Choose a writable folder and try again.",
            ),
        )
