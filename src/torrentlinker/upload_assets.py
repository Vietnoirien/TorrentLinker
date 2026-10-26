"""Private immutable Presentation Images, stored in application data by stable ID."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

MAX_IMAGE = 8_000_000


def image_mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Use PNG, JPEG or WebP image bytes.")


def inline_image(value):
    """Recognize only bounded image data emitted from private saved assets."""
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)", value)
    if not match or len(value) > MAX_IMAGE * 4 // 3 + 100:
        return None
    try:
        data = base64.b64decode(match[2], validate=True)
        if image_mime(data) != match[1]:
            return None
        return data, match[1]
    except ValueError:
        return None


class Assets:
    def __init__(self, directory):
        self.directory = Path(directory) / "upload-assets"

    def put(self, data, mime, item_path, metadata=None):
        if not data or len(data) > MAX_IMAGE or image_mime(data) != mime:
            raise ValueError("Invalid image or image exceeds 8 MB.")
        from PIL import Image

        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 16_000_000:
                    raise ValueError("Presentation Image exceeds 16 million pixels.")
                image.verify()
        except (OSError, SyntaxError) as error:
            raise ValueError("Presentation Image cannot be decoded.") from error
        metadata = dict(metadata or {})
        # A content-addressed immutable asset cannot leak later revisions into old cards.
        identity = json.dumps({"item_path": item_path, "metadata": metadata}, sort_keys=True)
        identifier = hashlib.sha256(identity.encode() + data).hexdigest()
        self.directory.mkdir(parents=True, exist_ok=True)
        body = {
            "asset_id": identifier,
            "mime_type": mime,
            "item_path": item_path,
            "size_bytes": len(data),
            "metadata": metadata,
        }
        # Atomic publication; concurrent extraction of identical bytes is harmless.
        from tempfile import NamedTemporaryFile

        for suffix, content in ((".image", data), (".json", json.dumps(body).encode())):
            with NamedTemporaryFile(dir=self.directory, delete=False) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            temporary_path.replace(self.directory / (identifier + suffix))
        return body

    def read(self, identifier, item_path):
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise ValueError("Invalid asset ID.")
        try:
            metadata = json.loads((self.directory / (identifier + ".json")).read_text())
            if metadata["item_path"] != item_path:
                raise ValueError("Asset does not belong to this Local Item.")
            data = (self.directory / (identifier + ".image")).read_bytes()
        except OSError:
            raise ValueError("Saved Presentation Image is unavailable.") from None
        if len(data) > MAX_IMAGE or image_mime(data) != metadata["mime_type"]:
            raise ValueError("Saved Presentation Image is invalid.")
        return data, metadata["mime_type"]

    def inline(self, identifier, item_path):
        data, mime = self.read(identifier, item_path)
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"

    def extract(self, request, evidence):
        """Copy bounded artwork into application data; never publish it."""
        result = []
        source = str(request.item.path)
        for book in evidence.get("ebooks", []):
            path = request.item.save_path / book["file"]
            try:
                with zipfile.ZipFile(path) as archive:
                    for name in book.get("artwork", [])[:4]:
                        if archive.getinfo(name).file_size <= MAX_IMAGE:
                            data = archive.read(name)
                            result.append(
                                self.put(
                                    data,
                                    image_mime(data),
                                    source,
                                    {
                                        "origin": "embedded_epub",
                                        "file": book["file"],
                                        "member": name,
                                    },
                                )
                            )
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
        for file in request.files:
            path = request.item.save_path / file.local_path
            if len(result) >= 12:
                break
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                if file.size > MAX_IMAGE:
                    continue
                try:
                    data = path.read_bytes()
                    result.append(
                        self.put(
                            data,
                            image_mime(data),
                            source,
                            {
                                "origin": "local_artwork",
                                "file": file.local_path,
                            },
                        )
                    )
                except (OSError, ValueError):
                    continue
            elif request.category == 3 and not result:
                try:
                    import mutagen

                    audio = mutagen.File(path)
                    pictures = getattr(audio, "pictures", [])
                    if not pictures and getattr(audio, "tags", None):
                        pictures = (
                            audio.tags.getall("APIC") if hasattr(audio.tags, "getall") else []
                        )
                    for picture in pictures[:1]:
                        data = picture.data
                        result.append(
                            self.put(
                                data,
                                image_mime(data),
                                source,
                                {
                                    "origin": "embedded_audio",
                                    "file": file.local_path,
                                },
                            )
                        )
                except Exception:
                    continue
        return result
