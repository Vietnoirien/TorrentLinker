"""Action summary with an expandable, bounded JSON command viewer."""

import json
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QPalette, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.agent.presentation import request_command, request_summary


class JsonHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text):
        dark = QApplication.palette().color(QPalette.ColorRole.Base).lightness() < 128
        colors = (
            ["#82cfff", "#a7d58d", "#d5a6ff", "#ffbd78"]
            if dark
            else ["#005a9c", "#286b28", "#763aa0", "#945400"]
        )
        pattern = (
            r'"(?:\\.|[^"\\])*"\s*(?=:)|"(?:\\.|[^"\\])*"|'
            r"\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
        )
        for match in re.finditer(pattern, text):
            value = match.group()
            index = (
                0
                if text[match.end() :].lstrip().startswith(":")
                else 1
                if value.startswith('"')
                else 2
                if value in {"true", "false", "null"}
                else 3
            )
            style = QTextCharFormat()
            style.setForeground(QColor(colors[index]))
            start = len(text[: match.start()].encode("utf-16-le")) // 2
            length = len(value.encode("utf-16-le")) // 2
            self.setFormat(start, length, style)


class JsonCode(QPlainTextEdit):
    def __init__(self, value, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setPlainText(json.dumps(value, indent=2, ensure_ascii=False, default=str))
        self.highlighter = JsonHighlighter(self.document())
        self.setMinimumHeight(160)
        self.setMaximumHeight(320)
        self.setAccessibleName(self.tr("Full command (JSON)"))


class RequestDetails(QWidget):
    def __init__(self, event, parent=None, *, expanded=False):
        super().__init__(parent)
        self.setObjectName("requestDetails")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        language = QApplication.instance().property("language") or "en"
        for line in request_summary(event, language):
            label = QLabel(line)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        operation = (event.get("review") or {}).get("operation", {})
        if (
            operation.get("kind") == "edit-queue-selection"
            and operation.get("queue_action") == "remove"
        ):
            targets = QPlainTextEdit()
            targets.setObjectName("queueRemovalTargets")
            targets.setReadOnly(True)
            targets.setAccessibleName(request_summary(event, language)[0])
            targets.setPlainText(
                "\n\n".join(
                    f"{i}. {row['title']}\n{row.get('hash') or row['key']}\n{row['folder']}"
                    for i, row in enumerate(operation.get("selection_rows", []), 1)
                )
            )
            targets.setMinimumHeight(160)
            targets.setMaximumHeight(240)
            layout.addWidget(targets)
        self.toggle = QToolButton()
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.code = JsonCode(request_command(event))
        layout.addWidget(self.toggle)
        layout.addWidget(self.code)
        self.toggle.toggled.connect(self.expand)
        self.toggle.setChecked(expanded)
        self.expand(expanded)

    def expand(self, checked):
        self.code.setVisible(checked)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.toggle.setText(
            self.tr("Hide full command") if checked else self.tr("Show full command")
        )
