from PySide6.QtCore import Qt

from torrentlinker.gui.chat_folders import ChatFolders


def test_conversations_are_grouped_and_refresh_preserves_selection_and_collapsed_folders(qtbot):
    folders = ChatFolders()
    qtbot.addWidget(folders)
    rows = [
        {"id": "film", "name": "Find a film", "folder": "film_research"},
        {"id": "upload", "name": "Upload my film", "folder": "uploads"},
        {"id": "older", "name": "An older conversation"},
    ]
    folders.set_rows(rows, "film")
    folders.show()
    assert folders.topLevelItemCount() == 3
    films, uploads = folders.topLevelItem(0), folders.topLevelItem(1)
    assert films.text(0) == "Film research"
    selected = []
    folders.conversationSelected.connect(selected.append)
    folders.setCurrentItem(uploads.child(0))
    assert selected == ["upload"]
    films.setExpanded(False)
    rows[1]["name"] = "Upload prepared"
    folders.set_rows(rows, "upload")
    assert not folders.topLevelItem(0).isExpanded()
    assert folders.currentItem().text(0) == "Upload prepared"
    assert selected == ["upload"]
    rows[1]["folder"] = "Custom collection"
    folders.set_rows(rows, "upload")
    assert folders.currentItem().parent().text(0) == "Custom collection"
    assert folders.currentItem().data(0, Qt.UserRole) == "upload"
    folders.select_id("")
    assert folders.currentItem() is None


def test_native_move_dialog_pins_custom_folder_and_can_enable_automatic_classification(
    qtbot, tmp_path
):
    from fastapi.testclient import TestClient
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialogButtonBox

    from tests.test_assistant import login
    from torrentlinker.gui.assistant import AssistantTab
    from torrentlinker.web.app import create_app

    app = create_app(tmp_path, password="test-password-long")
    with TestClient(app) as browser:
        login(browser)
        model = browser.post(
            "/api/setup/assistant/providers",
            json={"name": "Local", "kind": "ollama", "model": "test"},
        ).json()["id"]
        chat = browser.post(
            "/api/assistant/conversations",
            json={
                "name": "Film ideas",
                "provider_id": model,
                "policy": {"name": "Read", "clients": ["default"]},
            },
        ).json()
        tab = AssistantTab(lambda: app.state.assistant)
        qtbot.addWidget(tab)
        tab.show()
        tab.activate()
        tab.select_conversation(chat["id"])

        def choose_custom():
            dialog = QApplication.activeModalWidget()
            # A custom name may equal a translated built-in label; retain its identity.
            dialog.findChild(QComboBox).setEditText("Uploads")
            assert not dialog.findChild(QCheckBox).isChecked()
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, choose_custom)
        tab.move_chat.click()
        stored = browser.get("/api/assistant/conversations").json()[0]
        assert (stored["folder"], stored["folder_source"]) == ("Uploads", "manual")
        assert tab.conversations.currentItem().parent().text(0) == "Uploads"

        def enable_auto():
            dialog = QApplication.activeModalWidget()
            dialog.findChild(QCheckBox).setChecked(True)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, enable_auto)
        tab.move_chat.click()
        stored = browser.get("/api/assistant/conversations").json()[0]
        assert stored["folder"] == "Uploads"
        assert stored["folder_source"] == "auto"
