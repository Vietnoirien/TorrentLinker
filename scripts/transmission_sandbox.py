"""Make a throwaway Transmission in Docker ready for the integration tests.

    data=$(mktemp -d)
    docker run -d --rm --name tl-transmission -p 127.0.0.1:19091:9091 \\
        -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:$data" lscr.io/linuxserver/transmission:4.1.3
    python scripts/transmission_sandbox.py http://127.0.0.1:19091
    TL_TRANSMISSION_SANDBOX=http://127.0.0.1:19091 TL_TRANSMISSION_DATA="$data" \\
        pytest tests/test_transmission_integration.py
    docker stop tl-transmission

Waits for the RPC and turns DHT, PeX, LPD, uTP and port forwarding off. Transmission's
own defaults are kept otherwise, including "Append .part to incomplete files' names".
"""

import sys
import time

import httpx

url = sys.argv[1].rstrip("/") + "/transmission/rpc"
session = ""
for _ in range(60):
    try:
        reply = httpx.post(
            url,
            json={"method": "session-get"},
            headers={"X-Transmission-Session-Id": session},
            timeout=5,
        )
        if reply.status_code == 409:
            session = reply.headers["X-Transmission-Session-Id"]
            continue
        if reply.status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise SystemExit("Transmission's RPC did not answer")
settings = {
    "dht-enabled": False,
    "pex-enabled": False,
    "lpd-enabled": False,
    "utp-enabled": False,
    "port-forwarding-enabled": False,
}
reply = httpx.post(
    url,
    json={"method": "session-set", "arguments": settings},
    headers={"X-Transmission-Session-Id": session},
    timeout=5,
).json()
if reply["result"] != "success":
    raise SystemExit(f"session-set: {reply['result']}")
version = httpx.post(
    url,
    json={"method": "session-get", "arguments": {"fields": ["version"]}},
    headers={"X-Transmission-Session-Id": session},
    timeout=5,
).json()
print("Transmission", version["arguments"]["version"], "ready")
