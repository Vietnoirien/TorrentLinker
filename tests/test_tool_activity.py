import json

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from torrentlinker.gui.chat_transcript import ChatTranscript, MessageText
from torrentlinker.gui.request_details import JsonCode


@pytest.mark.parametrize(
    "operation",
    [
        "search",
        '["search"]',
        ["search"],
        42,
        {"kind": ["search"]},
        {"kind": "manage", "action": ["pause"]},
        {"kind": "enqueue", "hashes": 42},
        {"kind": "search", "path": ["/media"]},
    ],
)
def test_rejected_tool_operation_remains_readable_in_chat(qtbot, operation):
    from torrentlinker.agent.presentation import request_summary, tool_description

    run = narrative_run()
    event = {
        "tool": "propose_action",
        "status": "failed",
        "after_message_index": 1,
        "arguments": {"operation": operation},
        "result": {"error": "Invalid operation: expected an object"},
    }
    run["events"] = [event]
    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.set_runs([run], str)
    transcript.findChild(QToolButton, "toolActivitySummary").click()
    transcript.findChild(QToolButton, "toolEventSummary").click()
    code = transcript.findChild(JsonCode)
    assert json.loads(code.toPlainText())["arguments"]["operation"] == operation
    # Both web history summaries and native fallback descriptions must remain readable.
    assert "propose_action" in request_summary(event)[0]
    assert tool_description(event) == "Run the requested application action."


def test_json_encoded_operation_uses_same_summary_as_validated_object():
    from torrentlinker.agent.presentation import request_summary, tool_description

    operation = {"kind": "enqueue", "client_id": "default", "hashes": ["a" * 40]}
    plain = {"tool": "propose_action", "arguments": {"operation": operation}}
    encoded = {"tool": "propose_action", "arguments": {"operation": json.dumps(operation)}}
    for language in ("en", "fr"):
        assert request_summary(encoded, language) == request_summary(plain, language)
        assert tool_description(encoded, language) == tool_description(plain, language)


@pytest.mark.parametrize("nested", [False, True])
def test_tool_error_stays_collapsed_until_details_are_opened(qtbot, nested):
    run = narrative_run()
    error = "Choose an allowed client. <b>Keep this literal.</b>"
    run["events"][0]["result"] = (
        {"job": {"status": "failed", "error": error}} if nested else {"error": error}
    )
    # Legacy events called even failed tool results 'finished'.
    run["events"][0]["status"] = "finished"
    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.set_runs([run], str)
    transcript.show()
    group = transcript.findChild(QToolButton, "toolActivitySummary")
    assert "failed" in group.text()
    assert "#" in group.styleSheet()
    error_label = transcript.findChild(QLabel, "toolActivityError")
    assert not error_label.isVisible() and error_label.text() == error
    assert error_label.textFormat() == Qt.TextFormat.PlainText
    group.click()
    entry = transcript.findChild(QToolButton, "toolEventSummary")
    assert "failed" in entry.text()
    assert entry.styleSheet() == group.styleSheet()
    assert not error_label.isVisible()
    entry.click()
    assert error_label.isVisible()
    assert transcript.findChildren(JsonCode)
    group.click()
    assert not error_label.isVisible()


def narrative_run():
    return {
        "id": "narrative",
        "status": "completed",
        "error": "",
        "calls": 2,
        "tokens": 100,
        "created": 1,
        "messages": [
            {"role": "user", "content": "Help me configure the folder."},
            {
                "role": "assistant",
                "content": "I will check the folder guide.",
                "phase": "commentary",
            },
            {
                "role": "assistant",
                "content": "Choose your Download Folder in Settings.",
                "phase": "final",
            },
        ],
        "events": [
            {
                "tool": "read_documentation",
                "status": "completed",
                "after_message_index": 1,
                "arguments": {"document_id": "guide/en/getting-started.md"},
                "result": {"text": "Set your folder", "code": "<script>unsafe</script>"},
                "description": {"en": "Read the setup guide", "fr": "Lire le guide de démarrage"},
            }
        ],
    }


def test_tool_activity_is_readable_inline_expandable_and_preserves_its_place(qtbot, tmp_path):
    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.resize(900, 900)
    run = narrative_run()
    transcript.set_runs([run], str)
    transcript.show()
    messages = transcript.findChildren(MessageText)
    activity = transcript.findChild(QToolButton, "toolActivitySummary")
    assert activity is not None
    assert "read_documentation" not in activity.text()
    assert not transcript.findChildren(JsonCode)
    dark = QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
    assert (messages[1].palette().color(QPalette.ColorRole.Text).lightness() > 128) == dark

    def position(child):
        return child.mapTo(transcript.widget(), QPoint()).y()

    assert position(messages[1]) < position(activity) < position(messages[2])
    activity.click()
    entry = transcript.findChild(QToolButton, "toolEventSummary")
    assert entry.isVisible()
    assert "read_documentation" not in entry.text()
    entry.click()
    code = transcript.findChild(JsonCode)
    assert code.isVisible()
    assert json.loads(code.toPlainText())["result"] == run["events"][0]["result"]
    assert code.height() <= 320
    transcript.set_runs([run], str)
    assert transcript.findChild(QToolButton, "toolActivitySummary").isChecked()
    assert transcript.findChild(QToolButton, "toolEventSummary").isChecked()
    qtbot.waitUntil(lambda: transcript.findChild(JsonCode).isVisible())
    transcript.grab().save(str(tmp_path / "chat-tool-activity.png"))


def test_long_tool_summaries_shorten_instead_of_widening_a_narrow_chat(qtbot):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from torrentlinker.gui.tool_activity import ElidedToolButton

    long = "Select Catalogue torrents and calculate exact totals for every chosen category"
    holder = QWidget()
    qtbot.addWidget(holder)
    button = ElidedToolButton()
    QVBoxLayout(holder).addWidget(button)
    button.setText(long)
    holder.resize(220, 60)
    holder.show()
    qtbot.waitUntil(lambda: button.width() <= 220)
    assert holder.minimumSizeHint().width() < 120
    assert button.text() == long  # the full label stays available
    shown = QToolButton.text(button)
    assert shown.endswith("…") and len(shown) < len(long)
    # A transcript holding such summaries fits a narrow chat panel.
    run = narrative_run()
    for event in run["events"]:
        event["description"] = {"en": long, "fr": long}
    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.resize(320, 600)
    transcript.show()
    transcript.set_runs([run], str)
    qtbot.waitUntil(lambda: transcript.widget().width() <= transcript.viewport().width())
