#!/usr/local/bin/python
"""Disposable substitute for the web executable in container integration tests."""

import json
import os
import sys
import time
from pathlib import Path

if os.getenv("PROBE_ORPHAN"):
    pid = os.fork()
    if pid == 0:
        if os.fork() == 0:
            time.sleep(0.2)
            os._exit(0)
        os._exit(0)
    os.waitpid(pid, 0)
    time.sleep(1)
    zombies = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            if path.read_text().split(") ", 1)[1].startswith("Z "):
                zombies.append(path.parent.name)
        except FileNotFoundError:
            pass
    print(json.dumps({"zombies": zombies}), flush=True)
else:
    writable = {}
    for variable in ("HOME", "XDG_CACHE_HOME", "TMPDIR"):
        path = Path(os.environ[variable]) / "probe"
        path.write_text("non-root write")
        writable[variable] = str(path.parent)
    ownership = {}
    for name in json.loads(os.environ.get("PROBE_PATHS", "[]")):
        info = os.lstat(name)
        ownership[name] = [info.st_uid, info.st_gid, info.st_mode & 0o7777]
    caps = {
        line.split(":")[0]: line.split(":")[1].strip()
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith(("CapEff:", "CapPrm:", "CapInh:", "CapAmb:", "NoNewPrivs:"))
    }
    print(
        json.dumps(
            {
                "uid": os.getuid(),
                "gid": os.getgid(),
                "groups": os.getgroups(),
                "writable": writable,
                "ownership": ownership,
                "caps": caps,
                "secret_file": os.getenv("TL_WEB_PASSWORD_FILE"),
                "args": sys.argv[1:],
            }
        ),
        flush=True,
    )
