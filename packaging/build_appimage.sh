#!/usr/bin/env bash
# Wrap the PyInstaller one-dir build (dist/torrentlinker) into dist/TorrentLinker-x86_64.AppImage.
set -euo pipefail
cd "$(dirname "$0")/.."

APPIMAGETOOL_VERSION=1.9.0
tool=build/appimagetool
if [ ! -x "$tool" ]; then
  mkdir -p build
  curl -fsSL -o "$tool" \
    "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
  chmod +x "$tool"
fi

appdir=build/AppDir
rm -rf "$appdir"
mkdir -p "$appdir/usr/bin"
cp -a dist/torrentlinker/. "$appdir/usr/bin/"
# Use the host compiler runtime together with its Mesa/LLVM drivers. The runtime
# collected on Ubuntu 22.04 can lack symbols required by newer system drivers,
# preventing GLX initialization. Remove versioned files and symlinks, including
# nested copies; keep the original PyInstaller output untouched.
find "$appdir/usr/bin" \( -type f -o -type l \) \
  \( -name 'libstdc++.so*' -o -name 'libgcc_s.so*' \) -delete
cp packaging/torrentlinker.desktop "$appdir/"
cp src/torrentlinker/assets/icon.png "$appdir/torrentlinker.png"
cat > "$appdir/AppRun" <<'RUN'
#!/bin/sh
here="$(dirname "$(readlink -f "$0")")"
exec "$here/usr/bin/torrentlinker" "$@"
RUN
chmod +x "$appdir/AppRun"

APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$tool" "$appdir" dist/TorrentLinker-x86_64.AppImage
