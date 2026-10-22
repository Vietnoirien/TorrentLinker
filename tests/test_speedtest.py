import httpx
import pytest

from torrentlinker.speedtest import CHUNK, SPEED_TEST_URL, measure_download_speed


def ticking(step: float):  # type: ignore[no-untyped-def]
    now = [0.0]

    def clock() -> float:
        now[0] += step
        return now[0]

    return clock


def test_speed_is_the_bytes_received_over_the_time_taken() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"x" * 1000)

    http = httpx.Client(transport=httpx.MockTransport(handler))

    speed = measure_download_speed(http, streams=1, duration=2, clock=ticking(0.5))

    assert speed == pytest.approx(2000 / 2.5)  # two requests before the deadline
    assert str(seen[0].url).startswith(SPEED_TEST_URL)
    assert seen[0].url.params["bytes"] == str(CHUNK)
    assert "authorization" not in seen[0].headers and "cookie" not in seen[0].headers


def test_a_refused_speed_test_raises() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))

    with pytest.raises(httpx.HTTPStatusError):
        measure_download_speed(http, streams=1, duration=2, clock=ticking(0.5))
