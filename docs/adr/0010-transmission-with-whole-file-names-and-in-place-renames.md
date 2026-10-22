# Transmission, with whole file names and renames in place

Transmission joins qBittorrent and Deluge as a Torrent Client, through its RPC (`transmission.py`), behind the same port as Deluge (ADR-0009). It needs only its address, and a username and password when remote access asks for them. Transmission 4.1.3 is tested in CI, in Docker, with the data at the same path and as `/data`.

Most of the port maps directly: Transmission has several labels per torrent, which stand for the port's tags as they are; it reports a bitfield of the pieces it has; it says when a torrent is already there; its statuses are translated into qBittorrent's names. Unlike Deluge, it checks a stopped torrent without starting it, so no speed guard is needed.

## .part names

When "Append .part to incomplete files' names" (`rename-partial-files`) is on, which is Transmission's default, Transmission renames on disk any file it finds incomplete. A Reseed's check finds the user's file incomplete whenever a piece it shares with an absent file is missing (a Partial Match) or when the data differs (a failed Verification): the user's `book.epub` became `book.epub.part`, and stayed so after the torrent was removed. Tried on 4.1.3 with each combination of that setting and of the incomplete-files folder: with the setting off the files are never renamed; the folder makes no difference.

So adding a Reseed is refused while the setting is on, before anything is added, and the connection test is refused too. The refusal offers to turn the setting off, which the user decided: TorrentLinker asks once, explaining that it applies to all of Transmission's torrents, and turns it off only if the user agrees, then runs the Reseed or the test again. Plan downloads are not refused: their files are new, and `.part` names do no harm there.

## Renames in place

Transmission renames one file or folder name at a time (`torrent-rename-path`), and a renamed folder takes every file inside it along. It cannot move a file into another folder. A rename keeping the same depth is made name by name, folders first; one that would need other folders, or a name that is already taken, is refused, and the Reseed flow then removes the torrent (never the data) and says why. Absent files of a Partial Match may follow their renamed folder, so the flow now waits only for the local files to be at their own paths.

## Consequences

- With Transmission, Matches whose local layout has another depth than the torrent's (for example a flattened folder) cannot be Reseeded. A future version could hardlink instead, which ADR-0002 set aside.
- The Review panel and the connection test offer to turn the setting off; a Reseed sent with a Plan only reports the refusal.
