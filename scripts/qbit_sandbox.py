"""Write a throwaway qBittorrent profile for integration tests.

    python scripts/qbit_sandbox.py <profile-dir> [port] [--auth]
    qbittorrent-nox --profile=<profile-dir>      # or: qbittorrent --profile=<profile-dir>
    TL_QBIT_SANDBOX=http://127.0.0.1:<port> pytest tests/test_qbit_integration.py

The instance listens on 127.0.0.1 only, accepts localhost without login (a random
login is still set, as qBittorrent 5 requires one), and has DHT, PeX and LSD off.
With --auth, localhost must log in too: the user is "sandbox" and the random password
is written to <profile-dir>/password.
"""

import base64
import hashlib
import os
import secrets
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if a != "--auth"]
auth = "--auth" in sys.argv[1:]
profile = Path(args[0]).resolve()
port = args[1] if len(args) > 1 else "18080"
password = secrets.token_urlsafe(18)
salt = os.urandom(16)
key = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100_000, dklen=64)
pbkdf2 = f"@ByteArray({base64.b64encode(salt).decode()}:{base64.b64encode(key).decode()})"

config = profile / "qBittorrent" / "config"
config.mkdir(parents=True, exist_ok=True)
(config / "qBittorrent.conf").write_text(
    f"""[LegalNotice]
Accepted=true

[BitTorrent]
Session\\QueueingSystemEnabled=false
Session\\DHTEnabled=false
Session\\PeXEnabled=false
Session\\LSDEnabled=false
Session\\Port=46881
Session\\DefaultSavePath={profile / "downloads"}

[Preferences]
WebUI\\Enabled=true
WebUI\\Address=127.0.0.1
WebUI\\Port={port}
WebUI\\Username=sandbox
WebUI\\Password_PBKDF2="{pbkdf2}"
WebUI\\LocalHostAuth={"true" if auth else "false"}
WebUI\\HostHeaderValidation=false
WebUI\\CSRFProtection=false
General\\StartMinimized=true
General\\SystemTrayEnabled=false

[Meta]
MigrationVersion=8
""",
    encoding="utf-8",
)
if auth:
    (profile / "password").write_text(password, encoding="utf-8")
    (profile / "password").chmod(0o600)
print(profile)
