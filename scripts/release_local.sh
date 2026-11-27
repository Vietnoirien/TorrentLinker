#!/usr/bin/env bash
# Build and publish a release from this machine, while GitHub Actions minutes are out.
#
#   scripts/release_local.sh v1.0.0-beta.49 [--no-image] [--dry-run]
#
# Mirrors release.yml for Linux, the container image and the companion zip. The
# Windows and macOS builds are not produced here. Set the repo variable
# LOCAL_RELEASES=true first so the tag does not start release.yml:
#   gh variable set LOCAL_RELEASES --body true
# Needs docker, gh (logged in, with access to the private Catalogue repository) and,
# for the image, `docker login ghcr.io` with a write:packages token.
set -euo pipefail
cd "$(dirname "$0")/.."

tag=${1:?usage: release_local.sh <tag> [--no-image] [--dry-run]}
shift
image=1 dry=0
for arg in "$@"; do
  case $arg in
    --no-image) image=0 ;;
    --dry-run) dry=1 ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done
[[ $tag == v* ]] || { echo "tag must start with v" >&2; exit 2; }
notes=docs/releases/$tag.md
[ -f "$notes" ] || { echo "missing $notes" >&2; exit 1; }
gh variable list --json name,value --jq '.[] | select(.name=="LOCAL_RELEASES") | .value' 2>/dev/null | grep -qx true || [ $dry = 1 ] \
  || { echo "set LOCAL_RELEASES=true first, or the tag starts release.yml" >&2; exit 1; }
git fetch -q origin main
commit=$(git rev-parse HEAD)
[ $dry = 1 ] || [ "$commit" = "$(git rev-parse origin/main)" ] || { echo "HEAD is not origin/main: push first" >&2; exit 1; }
git cat-file -e "$commit:$notes" || { echo "$notes is not committed" >&2; exit 1; }

# The committed tree only: uncommitted edits in this checkout never ship.
work=$(mktemp -d)
trap 'docker run --rm -v "$work:/w" ubuntu:22.04 rm -rf /w/src 2>/dev/null; rm -rf "$work"' EXIT
mkdir "$work/src" "$work/dist"
git archive "$commit" | tar -x -C "$work/src"

# The Catalogue, sealed with a fresh key; a release refuses an export older than 48 h.
gh release download catalogue --repo Vietnoirien/torrentlinker-catalogue \
  --pattern catalogue.json.xz --dir "$work"
(cd "$work/src" && PYTHONPATH=src "$OLDPWD/.venv/bin/python" scripts/bundle_catalogue.py \
  "$work/catalogue.json.xz" $([ $dry = 1 ] || echo --max-age-hours 48))
rm "$work/catalogue.json.xz"

# AppImage on Ubuntu 22.04, as the CI runner: an older glibc keeps it starting on older distros.
docker run --rm --network host -e QT_QPA_PLATFORM=offscreen -e APPIMAGE_EXTRACT_AND_RUN=1 \
  -v "$work/src:/src" -v "$work/dist:/out" -w /src ubuntu:22.04 bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl ca-certificates file binutils libegl1 libgl1 libxkbcommon0 libfontconfig1 \
      libdbus-1-3 libxcb-cursor0 libpulse0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 \
      libxkbcommon-x11-0 desktop-file-utils \
      libnss3 libnspr4 libasound2 libxcomposite1 libxtst6 libxrandr2 libxdamage1 libxkbfile1 >/dev/null
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    ~/.local/bin/uv venv -q --python 3.12 /venv
    . /venv/bin/activate
    ~/.local/bin/uv pip install -q ".[package]"
    (cd packaging && pyinstaller --noconfirm --log-level WARN --distpath ../dist --workpath ../build torrentlinker.spec)
    python -c "from pathlib import Path; assert list(Path(\"dist/torrentlinker\").rglob(\"libpulse.so.0\")), \"PulseAudio library missing\""
    packaging/build_appimage.sh
    python -c "from pathlib import Path; bad=[p for g in (\"libstdc++.so*\",\"libgcc_s.so*\") for p in Path(\"build/AppDir\").rglob(g)]; assert not bad, bad"
    useradd -m smoke && runuser -u smoke -- env QT_QPA_PLATFORM=offscreen APPIMAGE_EXTRACT_AND_RUN=1 \
      timeout 120 dist/TorrentLinker-x86_64.AppImage --smoke-test
    cp dist/TorrentLinker-x86_64.AppImage /out/
    chown -R '"$(id -u):$(id -g)"' /out'

python3 - "$work" <<'PY'
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
work = Path(sys.argv[1])
source = work / 'src/src/torrentlinker/companion_extension'
assert (source / 'manifest.json').is_file()
with ZipFile(work / 'dist/TorrentLinker-companion.zip', 'w', ZIP_DEFLATED) as bundle:
    for path in sorted(source.iterdir()):
        if path.is_file():
            bundle.write(path, f'torrentlinker-companion/{path.name}')
PY

if [ $image = 1 ]; then
  docker build --network host -q -t torrentlinker:smoke "$work/src" >/dev/null
  pw=$work/pw; echo smoke-password > "$pw"; chmod 644 "$pw"
  docker rm -f tl-smoke >/dev/null 2>&1 || true
  docker run -d --name tl-smoke -p 127.0.0.1:18787:8787 -e TL_WEB_PASSWORD_FILE=/run/pw \
    -v "$pw:/run/pw:ro" torrentlinker:smoke >/dev/null
  ok=0
  for _ in $(seq 30); do curl -fsS http://127.0.0.1:18787/healthz >/dev/null 2>&1 && { ok=1; break; }; sleep 2; done
  [ $ok = 1 ] || docker logs tl-smoke
  docker rm -f tl-smoke >/dev/null
  [ $ok = 1 ] || { echo "container smoke test failed" >&2; exit 1; }
fi

ls -lh "$work/dist"
if [ $dry = 1 ]; then
  cp "$work"/dist/* dist/ 2>/dev/null || { mkdir -p dist && cp "$work"/dist/* dist/; }
  echo "dry run: assets copied to dist/, nothing published"
  exit 0
fi

version=${tag#v}
channel=$([[ $tag == *-* ]] && echo beta || echo latest)
if [ $image = 1 ]; then
  docker buildx build --platform linux/amd64,linux/arm64 --push \
    -t "ghcr.io/vietnoirien/torrentlinker:$version" -t "ghcr.io/vietnoirien/torrentlinker:$channel" "$work/src"
fi
prerelease=$([[ $tag == *-* ]] && echo --prerelease || echo --latest)
gh release create "$tag" --target "$commit" --title "TorrentLinker $tag" --notes-file "$notes" $prerelease \
  "$work/dist/TorrentLinker-x86_64.AppImage" "$work/dist/TorrentLinker-companion.zip"
echo "published $tag (Linux + companion$([ $image = 1 ] && echo ' + image'); no Windows/macOS build)"
