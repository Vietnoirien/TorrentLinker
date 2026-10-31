import json
from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from torrentlinker.gui.chat_transcript import ChatTranscript, MessageText
from torrentlinker.gui.request_details import JsonCode


def test_changed_chat_run_keeps_other_messages_and_expanded_receipts(qtbot):
    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    older = narrative_run()
    current = deepcopy(older)
    current["id"] = "current"
    transcript.set_runs([current, older], str)
    transcript.show()
    old_messages = transcript.findChildren(MessageText)[:3]
    activity = transcript.findChildren(QToolButton, "toolActivitySummary")[0]
    activity.click()
    transcript.findChildren(QToolButton, "toolEventSummary")[0].click()
    command = transcript.findChild(JsonCode)
    assert command.isVisible()
    current["messages"][-1]["content"] = "A new answer."
    transcript.set_runs([current, older], str)
    assert transcript.findChildren(MessageText)[:3] == old_messages, (
        "An unrelated response rebuilt the completed history"
    )
    assert transcript.findChild(JsonCode) is command
    assert transcript.findChildren(MessageText)[-1].toPlainText().strip() == "A new answer."
    qtbot.waitUntil(command.isVisible)


def test_chat_reuse_respects_language_theme_headings_and_removed_history(qtbot, qapp):
    from torrentlinker import i18n

    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    run = narrative_run()
    heading = "Original discussion"
    transcript.run_heading = lambda run: heading
    transcript.set_runs([run], str)
    original = transcript.findChildren(MessageText)[0]
    heading = "Renamed discussion"
    transcript.set_runs([run], str)
    assert transcript.findChild(QLabel, "runHeading").text() == heading
    assert transcript.findChildren(MessageText)[0] is not original
    previous_language = qapp.property("language")
    previous_palette = qapp.palette()
    translators = i18n.install(qapp, "fr")
    try:
        transcript.set_runs([run], str)
        activity = transcript.findChild(QToolButton, "toolActivitySummary")
        assert "Lire le guide" in activity.text()
        original = transcript.findChildren(MessageText)[0]
        palette = QPalette(previous_palette)
        dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        palette.setColor(
            QPalette.ColorRole.Window, Qt.GlobalColor.white if dark else Qt.GlobalColor.black
        )
        qapp.setPalette(palette)
        transcript.set_runs([run], str)
        assert transcript.findChildren(MessageText)[0] is not original
        transcript.set_runs([], str)
        assert not transcript.findChildren(MessageText)
        assert not transcript.findChildren(QToolButton, "toolActivitySummary")
        transcript.set_runs([run], str)
        assert len(transcript.findChildren(MessageText)) == 3
    finally:
        qapp.setPalette(previous_palette)
        for translator in translators:
            qapp.removeTranslator(translator)
        qapp.setProperty("language", previous_language)


def test_chat_incremental_history_keeps_chronology_when_runs_arrive_or_disappear(qtbot):
    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.resize(900, 900)
    transcript.show()
    transcript.run_heading = lambda run: run["id"]
    runs = [dict(narrative_run(), id=f"run-{i}") for i in range(3)]
    for rows in ([runs[1], runs[0]], [runs[2], runs[1], runs[0]], [runs[2], runs[0]]):
        transcript.set_runs(rows, str)
        qtbot.waitUntil(
            lambda count=len(rows): len(transcript.findChildren(QLabel, "runHeading")) == count
        )
        # Layout geometry settles on the next event-loop iteration.
        QApplication.processEvents()
        headings = transcript.findChildren(QLabel, "runHeading")
        headings.sort(key=lambda label: label.mapTo(transcript.widget(), QPoint()).y())
        assert [label.text() for label in headings] == [run["id"] for run in reversed(rows)]
        assert len(transcript.findChildren(MessageText)) == 3 * len(rows)


def test_unexecuted_success_claim_is_explicitly_marked_as_reply_only(qtbot):
    run = narrative_run()
    run.update(
        calls=1,
        events=[],
        messages=[
            {"role": "user", "content": "lance le telechargement"},
            {
                "role": "assistant",
                "content": "Téléchargement lancé, statut sent (1/1).",
                "phase": "final",
            },
        ],
    )
    transcript = ChatTranscript()
    qtbot.addWidget(transcript)
    transcript.set_runs([run], str)
    group = transcript.findChild(QToolButton, "toolActivitySummary")
    assert "No tools called" in group.text()
    assert "Reply only" in group.text()
    notice = transcript.findChild(QLabel, "assistantExecutionNotice")
    assert notice and notice.text() == "No application action was performed in this reply."
    assert not notice.isHidden()
    group.click()
    labels = [label.text() for label in transcript.findChildren(QLabel)]
    assert "Model calls: 1 · Tool calls: 0 · Tokens: 100" in labels


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
