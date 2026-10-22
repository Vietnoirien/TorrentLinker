"""Make a throwaway Deluge in Docker ready for the integration tests.

    data=$(mktemp -d)
    docker run -d --rm --name tl-deluge -p 127.0.0.1:18112:8112 \\
        -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:$data" lscr.io/linuxserver/deluge:2.2.0
    python scripts/deluge_sandbox.py http://127.0.0.1:18112
    TL_DELUGE_SANDBOX=http://127.0.0.1:18112 TL_DELUGE_DATA="$data" \\
        pytest tests/test_deluge_integration.py
    docker stop tl-deluge

Mount the data folder at "$data:/data" instead for tests/test_deluge_docker_paths.py.

Waits for the Web UI, logs in with the image's default password ("deluge"), connects it
to its daemon, enables the Label plugin and turns DHT, PeX, LSD, UPnP and NAT-PMP off.
"""

import sys
import time

import httpx

url = sys.argv[1].rstrip("/") + "/json"
http = httpx.Client(timeout=10)


def call(method: str, *params: object) -> object:
    reply = http.post(url, json={"method": method, "params": list(params), "id": 1}).json()
    if reply["error"]:
        raise SystemExit(f"{method}: {reply['error']}")
    return reply["result"]


for _ in range(60):
    try:
        if call("auth.login", "deluge"):
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise SystemExit("Deluge's Web UI did not answer")
for _ in range(30):
    if call("web.connected"):
        break
    hosts = call("web.get_hosts")
    if hosts:
        call("web.connect", hosts[0][0])  # type: ignore[index]
    time.sleep(1)
else:
    raise SystemExit("Deluge's Web UI did not connect to its daemon")
call(
    "core.set_config", {"dht": False, "lsd": False, "utpex": False, "upnp": False, "natpmp": False}
)
call("core.enable_plugin", "Label")
for _ in range(30):
    if "Label" in call("core.get_enabled_plugins"):  # type: ignore[operator]
        break
    time.sleep(0.5)
else:
    raise SystemExit("The Label plugin did not start")
print("Deluge", call("daemon.get_version"), "ready")
