"""The Library's read-only evidence and offline provenance inspector."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.gui.tasks import run_in_background
from torrentlinker.library_evidence import inspect_item
from torrentlinker.provenance import MAX_TORRENT_BYTES, Provenance
from torrentlinker.scan import scan_item


class EvidencePanel(QWidget):
    def __init__(self, directory: Path):
        super().__init__()
        self.repository = Provenance(directory)
        self.entry = None
        self.generation = 0
        self.stop = threading.Event()
        layout = QVBoxLayout(self)
        note = QLabel(
            self.tr(
                "Compare claims with MediaInfo. Original names are evidence, "
                "not proof of authorship."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.inspect_button = QPushButton(self.tr("Inspect metadata"))
        self.inspect_button.setObjectName("inspectLibraryEvidence")
        self.inspect_button.clicked.connect(self.inspect)
        self.import_button = QPushButton(self.tr("Import old torrents…"))
        self.import_button.setObjectName("importLibraryProvenance")
        self.import_button.clicked.connect(self.import_torrents)
        actions.addWidget(self.inspect_button)
        actions.addWidget(self.import_button)
        cancel = QPushButton(self.tr("Cancel"))
        cancel.clicked.connect(lambda: self.stop.set())
        actions.addWidget(cancel)
        layout.addLayout(actions)
        self.output = QTextBrowser()
        self.output.setReadOnly(True)
        self.output.setObjectName("libraryEvidenceReport")
        layout.addWidget(self.output)
        self.set_entry(None)

    def set_entry(self, entry):
        self.stop.set()
        self.generation += 1
        self.entry = entry
        self.inspect_button.setEnabled(entry is not None)
        self.import_button.setEnabled(entry is not None)
        self.output.clear()

    def run(self, fn):
        generation = self.generation
        self.stop = threading.Event()
        self.inspect_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.output.setPlainText(self.tr("Reading local evidence…"))

        def done(result):
            if generation != self.generation:
                return
            self.inspect_button.setEnabled(True)
            self.import_button.setEnabled(True)
            self.render(result)

        def failed(error):
            if generation == self.generation:
                self.output.setPlainText(str(error))
                self.inspect_button.setEnabled(True)
                self.import_button.setEnabled(True)

        stop = self.stop
        run_in_background(lambda: fn(stop), done, failed)

    def inspect(self):
        if self.entry is None:
            return
        selected = self.entry.item
        path = selected.path

        def work(stop):
            item = scan_item(path) if path.exists() else selected
            return {**inspect_item(item, stop), "provenance": self.repository.rows(item)}

        self.run(work)

    def import_torrents(self):
        if self.entry is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Import old torrents"), "", "*.torrent"
        )
        if not paths:
            return
        selected = self.entry.item
        path = selected.path

        def work(stop):
            item = scan_item(path) if path.exists() else selected
            for filename in paths[:100]:
                if stop.is_set():
                    raise ValueError("Import cancelled.")
                with Path(filename).open("rb") as stream:
                    data = stream.read(MAX_TORRENT_BYTES + 1)
                self.repository.inspect(item, data, stop)
            return {"observations": [], "unreadable": [], "provenance": self.repository.rows(item)}

        self.run(work)

    def render(self, result):
        from html import escape

        parts = []
        observations = result.get("observations", [])
        if observations:
            headings = [
                self.tr("File / source"),
                self.tr("Claim"),
                self.tr("Observed"),
                self.tr("Confidence"),
            ]
            parts.append(
                '<table cellspacing="0" cellpadding="8" width="100%"><tr>'
                + "".join('<th align="left">' + escape(h) + "</th>" for h in headings)
                + "</tr>"
            )
            for row in observations:
                cells = [
                    row["file"]
                    + " · "
                    + self.label(row["source"])
                    + " · "
                    + self.label(row["field"]),
                    row["claim"],
                    row["observed"],
                    self.label(row["confidence"]),
                ]
                parts.append(
                    "<tr>" + "".join("<td>" + escape(c) + "</td>" for c in cells) + "</tr>"
                )
            parts.append("</table>")
        for path in result.get("unreadable", []):
            parts.append("<p>" + escape(self.tr("MediaInfo unavailable: ") + path) + "</p>")
        for row in result.get("provenance", []):
            parts.append(
                "<h3>"
                + escape(row["name"])
                + "</h3><p>"
                + escape(self.label(row["status"]))
                + f" · {row['verified_bytes']:,} / {row['target_bytes']:,} bytes</p>"
            )
            for file in row["files"]:
                parts.append(
                    "<p>"
                    + escape(file["original"])
                    + " → "
                    + escape(file["local"] or ", ".join(file["candidates"]))
                    + "</p>"
                )
        self.output.setHtml(
            "".join(parts)
            or "<p>"
            + escape(
                self.tr("No inconsistencies reported. This does not certify the release origin.")
            )
            + "</p>"
        )

    def label(self, value):
        return {
            "filename": self.tr("Filename"),
            "embedded-title": self.tr("Embedded title"),
            "writing-application": self.tr("Writing application"),
            "nfo": "NFO",
            "resolution": self.tr("Resolution"),
            "video-codec": self.tr("Video codec"),
            "audio-codec": self.tr("Audio codec"),
            "audio-channels": self.tr("Audio channels"),
            "hdr": "HDR",
            "processing": self.tr("Processing clue"),
            "measured": self.tr("Measured contradiction"),
            "hint": self.tr("Clue only"),
            "review": self.tr("Review needed"),
            "verified": self.tr("Hash verified"),
            "unverified": self.tr("Unverified"),
            "ambiguous": self.tr("Ambiguous"),
            "partial": self.tr("Partially verified"),
            "stale": self.tr("File changed; verify again"),
        }.get(value, value)
