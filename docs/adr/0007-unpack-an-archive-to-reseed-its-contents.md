# Unpack an archive to Reseed what it holds

Library Folders of 3D models are often kept as .zip, .rar or .7z archives, while the tracker's torrents hold the same files unpacked. The comparison saw the archive as one file: its compressed size, 30 to 55% smaller for STL models, failed the size check, so these Candidates were never even compared. On the first Library checked, 9 of 52 archives had a Candidate whose size equals, to the byte, the archive's unpacked contents.

An archive Local Item is now also compared by what it holds: its listing of files and uncompressed sizes. Zip is read directly; rar and 7z through 7-Zip, or unrar for rar. Without those tools, rar and 7z archives are compared as plain files, as before. When the torrent matches the archive's contents better than the archive itself, the result is a Match inside the archive.

qBittorrent cannot seed from inside an archive, so such a Match offers one action: Unpack and Reseed. It unpacks into a new folder next to the archive (the archive's single top folder, or a folder named after it), then compares the unpacked files again and runs the usual Reseed with its Verification (ADR-0002). This extends ADR-0004: the app writes these files because it creates them, in a folder that must not exist yet. It never overwrites a file and never deletes the archive; if unpacking fails, it removes only the folder it was creating. Entries that would land outside that folder are refused.

Unpacking can write tens of gigabytes, so it is always the user's choice, made for one Match at a time after seeing the size and the free space. A Plan never proposes a Match inside an archive.
