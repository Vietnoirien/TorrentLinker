"""Keep usable research links while withholding private tracker and credential URLs."""

import re
from urllib.parse import parse_qsl, unquote, urlsplit


def safe_content(text: str) -> str:
    def clean(match):
        url = match.group(0)
        try:
            parsed = urlsplit(url)
            keys = [re.sub(r"[^a-z]", "", key.lower()) for key, _ in parse_qsl(parsed.query)]
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username
                or parsed.password
                or re.search(r"(?:announce|passkey|apikey|token)", unquote(parsed.path), re.I)
                or any(
                    any(
                        secret in key
                        for secret in (
                            "key",
                            "token",
                            "auth",
                            "password",
                            "secret",
                            "signature",
                            "credential",
                        )
                    )
                    or key in {"sig", "pass"}
                    for key in keys
                )
                or parsed.fragment
            ):
                return "[URL]"
            return url
        except ValueError:
            return "[URL]"

    return re.sub(r"(?:https?|udp|wss?)://[^\s<>\"'\[\]]+", clean, text)
