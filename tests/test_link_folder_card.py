"""Settings explains the Link Folder per client (#213): the card text follows the client type."""

from pathlib import Path

VIEW = Path("src/torrentlinker/web/static/settings/view.js")


def test_the_client_form_has_a_link_folder_card_with_required_or_optional():
    source = VIEW.read_text(encoding="utf-8")
    assert "linkFolderCard(data.client.client, requiresLinks, data.reseed_link_root)" in source
    # Required for the clients that cannot rename a torrent's paths, optional for the others.
    assert 'required ? say("Required", "Requis") : say("Optional", "Facultatif")' in source
    for client in ("qbittorrent", "deluge", "transmission"):
        assert f"{client}: [" in source
