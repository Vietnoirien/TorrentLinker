"""Explicit provider protocols. No implicit fallback or credential forwarding."""

from __future__ import annotations

import json
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

PRESETS = {
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "compatible": "",
}

SAMPLING_PROVIDERS = {"ollama", "lmstudio", "compatible"}


class InvalidModelResponse(ValueError):
    """Response cannot be used; no tools from this turn may execute."""


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    kind: Literal[
        "ollama", "lmstudio", "openai", "anthropic", "gemini", "mistral", "openrouter", "compatible"
    ]
    url: str = Field(default="", max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    context_window: int = Field(default=32768, ge=512, le=2000000)
    context_auto: bool = True
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    api_key: str | None = Field(default=None, max_length=4096, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def preserve_manual_context(cls, value):
        if isinstance(value, dict) and "context_auto" not in value:
            if value.get("context_window", 32768) != 32768:
                value = {**value, "context_auto": False}
        return value

    @model_validator(mode="after")
    def endpoint(self):
        if self.temperature is not None and self.kind not in SAMPLING_PROVIDERS:
            raise ValueError(
                "Sampling overrides require Ollama, LM Studio or a compatible endpoint."
            )
        self.url = (self.url or PRESETS[self.kind]).rstrip("/")
        parsed = urlsplit(self.url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) base URL without credentials, query or fragment.")
        return self


class ContextTooLong(ValueError):
    """The provider rejected the input context before running tools."""


class Models:
    def __init__(self, transport=None):
        self.transport = transport

    def request(self, provider: Provider, key: str, path: str, body=None, timeout=60):
        headers = {}
        if key:
            if provider.kind == "anthropic":
                headers["x-api-key"] = key
            elif provider.kind == "gemini":
                headers["x-goog-api-key"] = key
            else:
                headers["Authorization"] = "Bearer " + key
        if provider.kind == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        try:
            with httpx.Client(
                transport=self.transport, timeout=timeout, trust_env=False, follow_redirects=False
            ) as client:
                with client.stream(
                    "POST" if body is not None else "GET",
                    provider.url + path,
                    headers=headers,
                    json=body,
                ) as response:
                    if not response.is_success:
                        if response.status_code in {400, 413, 422}:
                            detail = bytearray()
                            for chunk in response.iter_bytes():
                                detail.extend(chunk[: 65536 - len(detail)])
                                if len(detail) >= 65536:
                                    break
                            reason = detail.decode("utf-8", errors="replace").lower()
                            if any(
                                marker in reason
                                for marker in (
                                    "context_length_exceeded",
                                    "maximum context length",
                                    "context window",
                                    "prompt is too long",
                                    "input is too long",
                                )
                            ):
                                raise ContextTooLong(
                                    "The model context is full. "
                                    "Check its configured context window."
                                )
                        raise ValueError(
                            f"Model provider returned HTTP {response.status_code}. "
                            "Check the endpoint, model, credentials and quota."
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 2_000_000:
                            raise ValueError("Model response exceeds the size limit.")
                    return json.loads(data)
        except (httpx.HTTPError, json.JSONDecodeError):
            raise ValueError(
                "Cannot reach the model provider or read its response. Check the "
                "address and model server."
            ) from None

    def context(self, provider, key):
        from torrentlinker.assistant.discovery import discover_context

        return discover_context(self, provider, key)

    def models(self, provider, key):
        result = self.request(provider, key, "/models")
        return [
            r.get("id", r.get("name", "")).removeprefix("models/")
            for r in result.get("data", result.get("models", []))
        ][:500]

    def turn(self, p, key, messages, tools, maximum=2048, timeout=60):
        """Append native protocol messages, preserving reasoning/signatures between tool turns."""
        specs = [{"type": "function", "function": t} for t in tools]
        if p.kind == "openai":
            body = {
                "model": p.model,
                "input": messages,
                "store": False,
                "max_output_tokens": maximum,
                "tools": [{"type": "function", **t, "strict": False} for t in tools],
            }
            result = self.request(p, key, "/responses", body, timeout)
            self.check_output(result)
            blocks = result.get("output", [])
            messages.extend(blocks)
            text = "\n".join(
                c.get("text", "")
                for b in blocks
                for c in b.get("content", [])
                if c.get("type") == "output_text"
            )
            calls = [
                {"id": b["call_id"], "name": b["name"], "arguments": b["arguments"]}
                for b in blocks
                if b.get("type") == "function_call"
            ]
            usage = result.get("usage", {}).get("total_tokens", 0)
        elif p.kind == "anthropic":
            body = {
                "model": p.model,
                "system": messages[0]["content"],
                "messages": messages[1:],
                "max_tokens": maximum,
                "tools": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "input_schema": t["parameters"],
                    }
                    for t in tools
                ],
            }
            result = self.request(p, key, "/messages", body, timeout)
            self.check_output(result)
            blocks = result.get("content", [])
            messages.append({"role": "assistant", "content": blocks})
            text = "\n".join(b["text"] for b in blocks if b.get("type") == "text")
            calls = [
                {"id": b["id"], "name": b["name"], "arguments": b["input"]}
                for b in blocks
                if b.get("type") == "tool_use"
            ]
            u = result.get("usage", {})
            usage = u.get("input_tokens", 0) + u.get("output_tokens", 0)
        elif p.kind == "gemini":
            body = {
                "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
                "contents": messages[1:],
                "generationConfig": {"maxOutputTokens": maximum},
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": t["name"],
                                "description": t["description"],
                                "parametersJsonSchema": t["parameters"],
                            }
                            for t in tools
                        ]
                    }
                ],
            }  # parameters are JSON schemas
            if not tools:
                body.pop("tools")
            result = self.request(
                p, key, "/models/" + quote(p.model, safe="") + ":generateContent", body, timeout
            )
            self.check_output(result)
            content = result.get("candidates", [{}])[0].get(
                "content", {"role": "model", "parts": []}
            )
            messages.append(content)
            text = "\n".join(b.get("text", "") for b in content["parts"] if not b.get("thought"))
            calls = [
                {
                    "id": str(i),
                    "name": b["functionCall"]["name"],
                    "arguments": b["functionCall"].get("args", {}),
                }
                for i, b in enumerate(content["parts"])
                if "functionCall" in b
            ]
            usage = result.get("usageMetadata", {}).get("totalTokenCount", 0)
        else:
            body = {
                "model": p.model,
                "messages": messages,
                "tools": specs,
                "max_tokens": maximum,
                "stream": False,
            }
            if p.temperature is not None:
                body["temperature"] = p.temperature
            result = self.request(p, key, "/chat/completions", body, timeout)
            self.check_output(result)
            message = result["choices"][0]["message"]
            messages.append(message)
            text = message.get("content") or ""
            calls = [{"id": b["id"], **b["function"]} for b in message.get("tool_calls", [])]
            usage = result.get("usage", {}).get("total_tokens", 0)
        for call in calls:
            if isinstance(call["arguments"], str):
                try:
                    call["arguments"] = json.loads(call["arguments"])
                except json.JSONDecodeError as error:
                    raise InvalidModelResponse(
                        "The model returned malformed tool arguments."
                    ) from error
            if not isinstance(call["arguments"], dict):
                raise InvalidModelResponse("The model returned invalid tool arguments.")
        return text, calls, usage

    @staticmethod
    def check_output(result):
        if (
            (result.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
            or result.get("stop_reason") == "max_tokens"
            or any(c.get("finish_reason") == "length" for c in result.get("choices", []))
            or any(c.get("finishReason") == "MAX_TOKENS" for c in result.get("candidates", []))
        ):
            raise InvalidModelResponse(
                "The model reached its output token limit. The response is incomplete. "
                "Request a shorter answer or increase the per-response output budget."
            )
        if result.get("status") == "incomplete":
            raise InvalidModelResponse(
                "The model provider returned an incomplete response. Please retry."
            )

    @staticmethod
    def user(p, text):
        return (
            {"role": "user", "parts": [{"text": text}]}
            if p.kind == "gemini"
            else {"role": "user", "content": text}
        )

    @staticmethod
    def image_blocks(p, images):
        """Translate bounded inline pixels without fetching paths or URLs."""
        import base64

        blocks = []
        total = 0
        for image in images:
            mime, data = image.get("mimeType"), image.get("data", "")
            if mime not in {"image/png", "image/jpeg", "image/webp"}:
                continue
            try:
                size = len(base64.b64decode(data, validate=True))
            except (ValueError, TypeError):
                continue
            total += size
            if total > 8_000_000 or len(blocks) >= 12:
                raise ValueError("Tool images exceed the model input limit.")
            if p.kind == "anthropic":
                blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": data},
                    }
                )
            elif p.kind == "gemini":
                blocks.append({"inlineData": {"mimeType": mime, "data": data}})
            else:
                url = f"data:{mime};base64,{data}"
                blocks.append(
                    {"type": "input_image", "image_url": url}
                    if p.kind == "openai"
                    else {"type": "image_url", "image_url": {"url": url}}
                )
        return blocks

    @classmethod
    def results(cls, p, messages, results):
        outputs, visuals = [], []
        for call, result in results:
            content = result.get("content")
            images = (
                [b for b in content if isinstance(b, dict) and b.get("type") == "image"]
                if isinstance(content, list)
                else []
            )
            clean = {**result}
            if images:
                clean["content"] = [
                    b for b in content if not isinstance(b, dict) or b.get("type") != "image"
                ]
            text = json.dumps(clean)
            pixels = cls.image_blocks(p, images)
            if p.kind == "anthropic":
                outputs.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": [{"type": "text", "text": text}, *pixels] if pixels else text,
                    }
                )
            elif p.kind == "gemini":
                outputs.append(
                    {"functionResponse": {"name": call["name"], "response": {"result": clean}}}
                )
                visuals.extend(pixels)
            else:
                outputs.append(
                    {"type": "function_call_output", "call_id": call["id"], "output": text}
                    if p.kind == "openai"
                    else {"role": "tool", "tool_call_id": call["id"], "content": text}
                )
                if pixels:
                    visuals.extend(
                        [
                            {
                                "type": "input_text" if p.kind == "openai" else "text",
                                "text": f"Images returned by {call['name']} ({call['id']}).",
                            },
                            *pixels,
                        ]
                    )
        if p.kind == "anthropic":
            messages.append({"role": "user", "content": outputs})
        elif p.kind == "gemini":
            messages.append({"role": "user", "parts": [*outputs, *visuals]})
        else:
            messages.extend(outputs)
            if visuals:
                messages.append({"role": "user", "content": visuals})

    def test(self, p, key):
        tools = [
            {
                "name": "connection_probe",
                "description": "Test the connection by returning the supplied value.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            }
        ]
        messages = [
            {"role": "system", "content": "You are testing a tool connection."},
            self.user(
                p,
                "Call connection_probe with value torrentlinker. After its result, say Connected.",
            ),
        ]
        _, calls, usage = self.turn(p, key, messages, tools, 512)
        if (
            len(calls) != 1
            or calls[0]["name"] != "connection_probe"
            or calls[0]["arguments"] != {"value": "torrentlinker"}
        ):
            raise ValueError(
                "Connected, but the model did not make the expected tool call. "
                "Choose a model with tool support."
            )
        self.results(p, messages, [(calls[0], {"value": "torrentlinker"})])
        text, calls, used = self.turn(p, key, messages, tools, 512)
        if calls or not text.strip():
            raise ValueError("The model did not finish the tool round trip. Choose another model.")
        return {
            "tool_calling": True,
            "tokens": usage + used,
            "message": "Connection and tool round trip succeeded.",
        }
