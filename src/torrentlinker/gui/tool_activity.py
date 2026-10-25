"""Compact, readable tool activity with opt-in command and result details."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from torrentlinker.agent.presentation import tool_description, tool_error
from torrentlinker.gui.request_details import JsonCode


class ToolActivity(QWidget):
    def __init__(
        self,
        run,
        indexed_events,
        key,
        expanded,
        expanded_events,
        status_text,
        receipt,
        *,
        dark=False,
    ):
        super().__init__()
        self.setObjectName("toolActivity")
        color = "#b0bdcd" if dark else "#4c596b"
        error_style = f"color: {'#ff9696' if dark else '#ad2020'};"
        self.setStyleSheet(
            f"QToolButton {{ color: {color}; background: transparent; border: none; "
            "text-align: left; padding: 5px 0; font-size: 12px; }"
            "QToolButton:hover { text-decoration: underline; }"
        )
        language = QApplication.instance().property("language") or "en"

        def description(event):
            return event.get("description", {}).get(language) or tool_description(event, language)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.toggle = QToolButton()
        self.toggle.setObjectName("toolActivitySummary")
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        usage = (
            self.tr("%1 calls · %2 tokens")
            .replace("%1", str(run["calls"]))
            .replace("%2", str(run["tokens"]))
        )
        failures = [(event, tool_error(event)) for _, event in indexed_events if tool_error(event)]
        label = (
            description(failures[-1][0])
            if failures
            else description(indexed_events[-1][1])
            if indexed_events
            else usage
        )
        count = f" · {len(indexed_events)}" if indexed_events else ""
        group_status = (
            next(
                (
                    event["status"]
                    for _, event in indexed_events
                    if event["status"] in {"running", "waiting", "failed"}
                ),
                "finished",
            )
            if indexed_events
            else run["status"]
        )
        if group_status == "waiting":
            group_status = run["status"]
        if failures:
            if group_status == "finished":
                group_status = "failed"
            self.toggle.setStyleSheet(error_style)
        self.toggle.setText(f"{label[:96]}{count} · {status_text(group_status)}")
        self.toggle.setToolTip(label)
        layout.addWidget(self.toggle)
        if failures:
            error_label = QLabel(failures[-1][1])
            error_label.setObjectName("toolActivityError")
            error_label.setTextFormat(Qt.TextFormat.PlainText)
            error_label.setWordWrap(True)
            error_label.setStyleSheet(error_style)
            error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(error_label)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details = QWidget()
        rows = QVBoxLayout(self.details)
        rows.setContentsMargins(16, 2, 4, 4)
        rows.setSpacing(2)
        rows.addWidget(QLabel(usage))
        self.scroll.setWidget(self.details)
        layout.addWidget(self.scroll)
        for index, event in indexed_events:
            entry = QWidget()
            content = QVBoxLayout(entry)
            content.setContentsMargins(0, 0, 0, 0)
            content.setSpacing(4)
            toggle = QToolButton()
            toggle.setObjectName("toolEventSummary")
            toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toggle.setCheckable(True)
            label = description(event)
            state = run["status"] if event["status"] == "waiting" else event["status"]
            error = tool_error(event)
            if error:
                state = "failed"
                toggle.setStyleSheet(error_style)
            toggle.setText(f"{label[:110]} · {status_text(state)}")
            toggle.setToolTip(label)
            content.addWidget(toggle)
            if error:
                error_label = QLabel(error)
                error_label.setTextFormat(Qt.TextFormat.PlainText)
                error_label.setWordWrap(True)
                error_label.setStyleSheet(error_style)
                error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                content.addWidget(error_label)
            payload = QWidget()
            body = QVBoxLayout(payload)
            body.setContentsMargins(0, 0, 0, 6)
            content.addWidget(payload)
            event_key = (run["id"], index)

            def show_event(
                checked,
                button=toggle,
                panel=payload,
                box=body,
                item=event,
                identity=event_key,
                position=index,
            ):
                if checked and not box.count():
                    box.addWidget(
                        JsonCode(
                            {
                                k: item[k]
                                for k in ("tool", "arguments", "result", "review")
                                if k in item
                            }
                        )
                    )
                    open_receipt = QPushButton(self.tr("Open receipt"))
                    open_receipt.setFlat(True)
                    open_receipt.clicked.connect(lambda checked=False, i=position: receipt(i))
                    box.addWidget(open_receipt)
                panel.setVisible(checked)
                button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
                expanded_events.add(identity) if checked else expanded_events.discard(identity)
                QTimer.singleShot(0, self.fit_details)

            toggle.toggled.connect(show_event)
            toggle.setChecked(event_key in expanded_events)
            show_event(toggle.isChecked())
            rows.addWidget(entry)

        def show(checked):
            self.scroll.setVisible(checked)
            self.toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
            expanded.add(key) if checked else expanded.discard(key)
            self.fit_details()

        self.toggle.toggled.connect(show)
        self.toggle.setChecked(key in expanded)
        show(self.toggle.isChecked())

    def fit_details(self):
        if isValid(self):
            self.details.layout().activate()
            self.scroll.setFixedHeight(min(280, max(36, self.details.sizeHint().height() + 4)))
