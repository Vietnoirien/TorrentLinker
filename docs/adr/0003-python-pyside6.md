# Python + PySide6 for the desktop app

The app must have a native GUI on Linux and Windows. We chose Python with PySide6 (Qt) over Rust (Tauri, Slint, iced) and C# (Avalonia) mainly for the ecosystem: `guessit` parses release names (title, year, season/episode, group, resolution) far better than anything available in Rust, `qbittorrent-api` absorbs the 4.x/5.x WebUI API differences, and `torf` reads .torrent files. Qt's model/view tables and trees fit the review screens. The cost is heavier packaging (PyInstaller bundles) and slower startup than a Rust binary.
