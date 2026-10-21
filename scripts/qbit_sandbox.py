"""Write a throwaway qBittorrent profile for integration tests.

    python scripts/qbit_sandbox.py <profile-dir> [port]
    qbittorrent-nox --profile=<profile-dir>      # or: qbittorrent --profile=<profile-dir>
    TL_QBIT_SANDBOX=http://127.0.0.1:<port> pytest tests/test_qbit_integration.py

The instance listens on 127.0.0.1 only, accepts localhost without login (a random
login is still set, as qBittorrent 5 requires one), and has DHT, PeX and LSD off.
"""

import base64
import hashlib
import os
import secrets
import sys
from pathlib import Path

profile = Path(sys.argv[1]).resolve()
port = sys.argv[2] if len(sys.argv) > 2 else "18080"
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
WebUI\\LocalHostAuth=false
WebUI\\HostHeaderValidation=false
WebUI\\CSRFProtection=false
General\\StartMinimized=true
General\\SystemTrayEnabled=false

[Meta]
MigrationVersion=8
""",
    encoding="utf-8",
)
print(profile)
