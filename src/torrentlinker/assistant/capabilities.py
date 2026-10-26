"""Harmless bounded model assessment. A failed probe never disables ordinary chat."""

from __future__ import annotations

import base64
import secrets
import struct
import time
import zlib


def probe_image():
    """Random stripe order, with no answer in the bytes or prompt metadata."""
    palette = [
        ("red", b"\xff\x00\x00"),
        ("blue", b"\x00\x00\xff"),
        ("green", b"\x00\xff\x00"),
        ("yellow", b"\xff\xff\x00"),
    ]
    secrets.SystemRandom().shuffle(palette)
    name = ",".join(name for name, _ in palette)
    stripe_row = b"".join(rgb * 16 for _, rgb in palette)

    def chunk(kind, data):
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 64, 32, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + stripe_row) * 32))
        + chunk(b"IEND", b"")
    )
    return name, {"type": "image", "mimeType": "image/png", "data": base64.b64encode(png).decode()}


def assess(models, provider, key):
    checks = {}
    tokens = 0
    tool = {
        "name": "assessment_probe",
        "description": "Harmless setup probe. No side effects.",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "count": {"type": "integer"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["value", "count", "labels"],
            "additionalProperties": False,
        },
    }

    def messages(text):
        return [
            {"role": "system", "content": "Follow the setup test instructions exactly."},
            models.user(provider, text),
        ]

    def turn(history, tools):
        nonlocal tokens
        text, calls, used = models.turn(provider, key, history, tools, 256, timeout=15)
        tokens += used
        return text, calls

    def record(name, action):
        try:
            ok, reason = action()
            checks[name] = {
                "status": "passed" if ok else "failed",
                "reason": reason,
                "failure_kind": None if ok else "model_behavior",
            }
        except (ValueError, KeyError, TypeError, IndexError) as error:
            checks[name] = {
                "status": "untested",
                "reason": str(error)[:400],
                "failure_kind": "connection_or_adapter",
            }

    state = {}
    nonce = secrets.token_hex(6)
    expected = {"value": nonce, "count": 3, "labels": ["a", "b"]}

    def structured():
        history = messages(f"Call assessment_probe with these exact arguments: {expected!r}.")
        _, calls = turn(history, [tool])
        ok = len(calls) == 1 and calls[0]["name"] == tool["name"]
        ok = ok and calls[0]["arguments"] == expected
        if ok:
            state.update(history=history, call=calls[0])
        return ok, "Exact structured arguments returned." if ok else "Unexpected tool or arguments."

    record("structured_arguments", structured)

    def result_handling():
        if not state:
            raise ValueError("Structured call unavailable; result handling was not tested.")
        token = secrets.token_hex(8)
        models.results(
            provider,
            state["history"],
            [
                (
                    state["call"],
                    {
                        "instruction": "Reply with only the following receipt.",
                        "receipt": token,
                    },
                )
            ],
        )
        text, calls = turn(state["history"], [tool])
        ok = not calls and text.strip().strip('"') == token
        return ok, "Receipt read from tool result." if ok else "Did not reproduce the tool receipt."

    record("tool_results", result_handling)

    def recovery():
        if not state:
            raise ValueError("Structured call unavailable; correction was not tested.")
        history = messages(f"Call assessment_probe with these exact arguments: {expected!r}.")
        _, calls = turn(history, [tool])
        if len(calls) != 1:
            return False, "No single call available to reject."
        models.results(
            provider,
            history,
            [
                (
                    calls[0],
                    {
                        "error": "Rejected: count must be 4. "
                        "Correct count and retry the same call.",
                    },
                )
            ],
        )
        _, corrected = turn(history, [tool])
        ok = len(corrected) == 1 and corrected[0]["name"] == tool["name"]
        ok = ok and corrected[0]["arguments"] == {**expected, "count": 4}
        return (
            ok,
            "Rejected arguments corrected." if ok else "Rejected arguments were not corrected.",
        )

    record("tool_correction", recovery)

    def vision(tool_result=False):
        colour, image = probe_image()
        prompt = (
            "Read the four vertical stripes left to right. Reply only with their "
            "colours comma-separated, without spaces, using red, blue, green, yellow."
        )
        history = messages(prompt)
        if tool_result:
            history = messages(
                "Call assessment_probe with value image, count 1, labels []. Then " + prompt
            )
            _, calls = turn(history, [tool])
            if len(calls) != 1 or calls[0]["name"] != tool["name"]:
                return False, "No image tool call returned."
            models.results(provider, history, [(calls[0], {"content": [image]})])
        else:
            pixels = models.image_blocks(provider, [image])
            if provider.kind == "gemini":
                history[-1]["parts"].extend(pixels)
            else:
                history[-1]["content"] = [
                    {
                        "type": "input_text" if provider.kind == "openai" else "text",
                        "text": prompt,
                    },
                    *pixels,
                ]
        text, calls = turn(history, [])
        ok = not calls and text.strip().lower().strip('."') == colour
        return (
            ok,
            "Inline image stripe order identified."
            if ok
            else "Inline image stripe order not identified.",
        )

    record("vision", vision)
    record("tool_images", lambda: vision(True))
    return {
        "endpoint": provider.url,
        "model": provider.model,
        "kind": provider.kind,
        "checked_at": time.time(),
        "checks": checks,
        "tokens": tokens,
        "tool_calling": checks["structured_arguments"]["status"] == "passed",
        "verified_vision": all(checks[n]["status"] == "passed" for n in ("vision", "tool_images")),
        "message": "Model assessment finished. Failed checks do not disable chat or drafting.",
    }
