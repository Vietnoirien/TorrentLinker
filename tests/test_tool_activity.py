import json

from PySide6.QtCore import QPoint
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QToolButton

from torrentlinker.gui.chat_transcript import ChatTranscript, MessageText
from torrentlinker.gui.request_details import JsonCode


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
