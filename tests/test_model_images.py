"""Actual image bytes cross each provider's public protocol boundary."""

import base64
import json

import httpx
import pytest

from torrentlinker.assistant.providers import Models, Provider


@pytest.mark.parametrize("kind", ["compatible", "openai", "anthropic", "gemini"])
def test_tool_images_reach_model_as_pixels(kind):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        responses = {
            "compatible": {"choices": [{"message": {"role": "assistant", "content": "red"}}]},
            "openai": {"output": []},
            "anthropic": {"content": []},
            "gemini": {"candidates": [{"content": {"role": "model", "parts": []}}]},
        }
        return httpx.Response(200, json=responses[kind])

    provider = Provider(name="test", kind=kind, url="http://localhost/v1", model="test")
    models = Models(httpx.MockTransport(handler))
    pixels = base64.b64encode(b"actual image bytes").decode()
    messages = [{"role": "system", "content": "Inspect"}]
    models.results(
        provider,
        messages,
        [
            (
                {"id": "call", "name": "render"},
                {
                    "asset_id": "owned-asset",
                    "content": [{"type": "image", "mimeType": "image/png", "data": pixels}],
                },
            )
        ],
    )
    models.turn(provider, "", messages, [])
    body = json.dumps(seen[0])
    assert pixels in body
    if kind == "compatible":
        assert seen[0]["messages"][-1]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;"
        )
    elif kind == "openai":
        assert seen[0]["input"][-1]["content"][1]["type"] == "input_image"
    elif kind == "anthropic":
        assert seen[0]["messages"][-1]["content"][0]["content"][1]["source"]["data"] == pixels
    else:
        assert seen[0]["contents"][-1]["parts"][1]["inlineData"]["data"] == pixels


def test_assessment_records_behavior_and_adapter_failures_independently():
    from torrentlinker.assistant.capabilities import assess

    def handler(request):
        body = json.loads(request.content)
        # The endpoint accepts normal calls but rejects all inline images.
        if "image_url" in request.content.decode():
            return httpx.Response(400)
        text = body["messages"][-1].get("content", "")
        if isinstance(text, str) and "exact arguments:" in text:
            import ast

            arguments = ast.literal_eval(text.split("arguments: ", 1)[1].rstrip("."))
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "probe",
                        "type": "function",
                        "function": {
                            "name": "assessment_probe",
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            }
        elif body["messages"][-1]["role"] == "tool":
            result = json.loads(text)
            if "receipt" in result:
                message = {"role": "assistant", "content": result["receipt"]}
            else:
                message = {"role": "assistant", "content": "Cannot correct"}
        else:
            message = {"role": "assistant", "content": "No tool"}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    provider = Provider(name="test", kind="compatible", url="http://localhost/v1", model="test")
    result = assess(Models(httpx.MockTransport(handler)), provider, "")
    assert result["checks"]["structured_arguments"]["status"] == "passed"
    assert result["checks"]["tool_results"]["status"] == "passed"
    assert result["checks"]["tool_correction"]["failure_kind"] == "model_behavior"
    assert result["checks"]["vision"]["failure_kind"] == "connection_or_adapter"
    assert result["verified_vision"] is False
    assert result["tool_calling"] is True


def test_image_context_counts_pixels_as_images_not_base64_prose():
    from torrentlinker.assistant.context import message_size

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + "A" * 900000},
                },
                {"type": "text", "text": "Inspect this render."},
            ],
        }
    ]
    assert 5000 < message_size(messages) < 10000
