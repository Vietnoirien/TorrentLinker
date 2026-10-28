"""Opt-in Docker acceptance tests against a locally built production image.

TL_DOCKER_TEST_IMAGE=torrentlinker:issue43-review pytest tests/test_container_docker.py
Only disposable containers and pytest temporary directories are mounted.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

_IMAGE = os.environ.get("TL_DOCKER_TEST_IMAGE")
pytestmark = pytest.mark.skipif(not _IMAGE, reason="set TL_DOCKER_TEST_IMAGE for Docker tests")
_ENTRYPOINT = ["python", "-m", "torrentlinker.container_entrypoint"]
_CAPS = [
    "--cap-drop=ALL",
    *[f"--cap-add={cap}" for cap in ("CHOWN", "DAC_OVERRIDE", "SETUID", "SETGID")],
]


def docker(*args, check=True):
    return subprocess.run(
        ["docker", *args],
        text=True,
        capture_output=True,
        check=check,
        timeout=90,
    )


@pytest.fixture(scope="module")
def probe_image(tmp_path_factory):
    directory = tmp_path_factory.mktemp("container-probe")
    shutil.copy(Path(__file__).parent / "fixtures/container_probe.py", directory / "probe.py")
    (directory / "Dockerfile").write_text(
        f"FROM {_IMAGE}\nCOPY --chmod=755 probe.py /usr/local/bin/torrentlinker-web\n"
    )
    name = f"torrentlinker-test:{uuid.uuid4().hex}"
    docker("build", "--network=none", "-q", "-t", name, str(directory))
    yield name
    docker("image", "rm", name)


def probe(image, *options, setup=None, args=()):
    command = ["run", "--rm", "--network=none", "--tmpfs", "/config:mode=777", *options]
    if setup:
        command += [
            "--entrypoint",
            "/bin/sh",
            image,
            "-ec",
            setup + '\nexec "$@"',
            "bootstrap",
            *_ENTRYPOINT,
            *args,
        ]
    else:
        command += [image, *args]
    return docker(*command, check=False)


def payload(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_default_nonroot_image(probe_image):
    data = payload(probe(probe_image, "--cap-drop=ALL"))
    assert (data["uid"], data["gid"]) == (1000, 1000)
    assert data["caps"]["CapEff"] == "0000000000000000"


@pytest.mark.parametrize("options", [[], _CAPS])
def test_root_switch_and_runtime_paths(probe_image, options):
    data = payload(
        probe(
            probe_image,
            "--user=0:0",
            *options,
            "--security-opt=no-new-privileges:true",
            "-e",
            "PUID=1001",
            "-e",
            "PGID=100",
            "-e",
            "TL_WEB_PASSWORD_FILE=/run/secrets/probe",
            args=("--port", "9876"),
        )
    )
    assert (data["uid"], data["gid"], data["groups"]) == (1001, 100, [])
    assert all(
        data["caps"][name] == "0000000000000000"
        for name in ("CapEff", "CapPrm", "CapInh", "CapAmb")
    )
    assert data["caps"]["NoNewPrivs"] == "1"
    assert data["secret_file"] == "/run/secrets/probe"
    assert data["args"] == ["--port", "9876"]
    assert set(data["writable"].values()) == {"/config/home", "/config/cache", "/config/tmp"}


def test_explicit_nonroot_preserves_groups_and_skips_repair(probe_image):
    data = payload(
        probe(
            probe_image,
            "--user=1234:2345",
            "--group-add=3456",
            "--cap-drop=ALL",
            "-e",
            "PUID=0",
            "-e",
            'PROBE_PATHS=["/config"]',
        )
    )
    assert (data["uid"], data["gid"]) == (1234, 2345)
    assert 3456 in data["groups"]
    assert data["ownership"]["/config"][:2] == [0, 0]


def test_ownership_repair_leaves_aliases_and_media_untouched(probe_image):
    paths = ["/config", "/config/state", "/external/media", "/config/link", "/config/hardlink"]
    setup = """
mkdir /external
printf media > /external/media
chown 1234:2345 /external/media
printf state > /config/state
chmod 640 /config/state
ln -s /external/media /config/link
ln /config/state /config/hardlink
# Use a regular state file independent of the hardlink pair.
mv /config/state /config/alias
printf state > /config/state
chmod 640 /config/state
"""
    data = payload(
        probe(
            probe_image,
            "--user=0:0",
            "-e",
            "PUID=1001",
            "-e",
            "PGID=100",
            "-e",
            f"PROBE_PATHS={json.dumps(paths)}",
            setup=setup,
        )
    )
    assert data["ownership"]["/config/state"] == [1001, 100, 0o640]
    assert data["ownership"]["/external/media"][:2] == [1234, 2345]
    assert data["ownership"]["/config/link"][:2] == [0, 0]
    assert data["ownership"]["/config/hardlink"][:2] == [0, 0]


def test_nested_same_device_bind_mount_is_not_changed(probe_image, tmp_path):
    config = tmp_path / "config"
    media = tmp_path / "media"
    config.mkdir(mode=0o777)
    config.chmod(0o777)
    media.mkdir(mode=0o755)
    (media / "file").write_text("media")
    before = {p.name: (p.stat().st_uid, p.stat().st_gid) for p in (media, media / "file")}
    try:
        result = docker(
            "run",
            "--rm",
            "--network=none",
            "--user=0:0",
            "-e",
            "PUID=1001",
            "-e",
            "PGID=100",
            "--mount",
            f"type=bind,src={config},dst=/config",
            "--mount",
            f"type=bind,src={media},dst=/config/media",
            "-e",
            'PROBE_PATHS=["/config/media", "/config/media/file"]',
            probe_image,
        )
        data = payload(result)
        assert config.stat().st_dev == media.stat().st_dev
        assert data["ownership"]["/config/media"][:2] == list(before["media"])
        assert data["ownership"]["/config/media/file"][:2] == list(before["file"])
    finally:
        # Remove only runtime dirs created in this test's bind mount, using the chosen UID.
        docker(
            "run",
            "--rm",
            "--network=none",
            "--user=1001:100",
            "--entrypoint=sh",
            "--mount",
            f"type=bind,src={config},dst=/config",
            probe_image,
            "-c",
            "rm -rf /config/home /config/cache /config/tmp",
        )


@pytest.mark.parametrize(
    "options,expected",
    [
        (["-e", "PUID=0"], "PUID must be"),
        (["-e", "PGID=abc"], "PGID must be"),
        (["--cap-drop=ALL"], "root initialization needs"),
    ],
)
def test_invalid_root_start_fails_closed(probe_image, options, expected):
    result = probe(probe_image, "--user=0:0", *options)
    assert result.returncode == 1
    assert expected in result.stderr
    assert not result.stdout


def test_readonly_config_warns_and_never_runs_root(probe_image, tmp_path):
    result = docker(
        "run",
        "--rm",
        "--network=none",
        "--user=0:0",
        "-e",
        "PUID=1001",
        "-e",
        "PGID=100",
        "--mount",
        f"type=bind,src={tmp_path},dst=/config,readonly",
        probe_image,
        check=False,
    )
    assert result.returncode == 1
    assert "continuing as 1001:100" in result.stderr
    assert "startup failed" in result.stderr
    assert not result.stdout


@pytest.mark.parametrize("options", [[], ["--init"]])
def test_tini_reaps_orphans_with_or_without_docker_init(probe_image, options):
    data = payload(probe(probe_image, *options, "-e", "PROBE_ORPHAN=1"))
    assert data["zombies"] == []


def test_real_web_server_health_and_sigterm():
    name = f"tl-issue43-{uuid.uuid4().hex}"
    docker(
        "run",
        "-d",
        "--name",
        name,
        "--network=none",
        "--user=0:0",
        *_CAPS,
        "--tmpfs",
        "/config",
        "-e",
        "PUID=1001",
        "-e",
        "PGID=100",
        "-e",
        "TL_WEB_PASSWORD=disposable-test-password",
        _IMAGE,
    )
    try:
        for _ in range(40):
            result = docker(
                "exec",
                name,
                "python",
                "-c",
                "import urllib.request; "
                "urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=1)",
                check=False,
            )
            if result.returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail(docker("logs", name).stdout + docker("logs", name).stderr)
        docker("stop", "--time=10", name)
        assert docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip() in {
            "0",
            "143",
        }, docker("logs", name).stderr
        assert "Application shutdown complete" in docker("logs", name).stderr
    finally:
        docker("rm", "-f", name)


@pytest.mark.parametrize("config_args", [[], ["--config", "/state"]])
def test_nonroot_custom_config_without_writable_default(probe_image, config_args):
    # /config is the image's 0700 directory, owned by another user.
    result = docker(
        "run",
        "--rm",
        "--network=none",
        "--user=1234:2345",
        "--cap-drop=ALL",
        "--tmpfs",
        "/state:uid=1234,gid=2345,mode=700",
        "-e",
        "TL_CONFIG_DIR=/state" if not config_args else "TL_CONFIG_DIR=/config",
        probe_image,
        *config_args,
    )
    data = payload(result)
    assert data["uid"] == 1234
    assert set(data["writable"].values()) == {"/state/home", "/state/cache", "/state/tmp"}
