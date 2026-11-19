"""Real Docker runtime isolation (opt-in, T06)."""
import os

import pytest

pytestmark = pytest.mark.integration


def test_runtime_is_nonroot_isolated_and_labeled():
    if os.environ.get("HARNESS_INTEGRATION") != "1":
        pytest.skip("Set HARNESS_INTEGRATION=1 and start a workspace")
    import docker
    client = docker.from_env()
    containers = [c for c in client.containers.list(all=True)
                  if c.labels.get("harness.installation") == os.environ.get("INSTALLATION_ID")]
    assert containers, "no labelled runtime container"
    for c in containers:
        cfg = c.attrs["HostConfig"]
        assert c.attrs["Config"]["User"] in ("10001:10001", "10001")
        assert cfg["ReadonlyRootfs"] is True
        assert "ALL" in cfg["CapDrop"]
        assert cfg["SecurityOpt"] == ["no-new-privileges:true"]
        binds = cfg.get("Binds") or []
        # HostConfig.Binds is a list of "volume:/path:mode" strings.
        mounts = [b.split(":")[0] for b in binds]
        assert len(mounts) >= 2  # project + dsh-home named volumes
        assert all(m.startswith("harness-") for m in mounts), mounts
        # Must be born only on its internal space network, never the default bridge.
        networks = list(c.attrs["NetworkSettings"]["Networks"].keys())
        assert len(networks) == 1 and networks[0].startswith("harness-"), networks
        assert "bridge" not in networks


def test_runtime_probe_blocks_host_and_internet():
    """Run the in-container isolation probe against every running runtime."""
    import shutil
    import subprocess
    from pathlib import Path

    if os.environ.get("HARNESS_INTEGRATION") != "1":
        pytest.skip("Set HARNESS_INTEGRATION=1 and start a workspace")
    if shutil.which("docker") is None:
        pytest.skip("docker CLI unavailable")
    probe = Path(__file__).resolve().parents[2] / "scripts" / "runtime_isolation_probe.py"
    cmd = ["docker", "ps", "--filter", "label=harness.resource=runtime", "--format", "{{.ID}}"]
    ids = subprocess.check_output(cmd, text=True).split()
    assert ids, "no runtime container"
    for cid in ids:
        result = subprocess.run(
            ["docker", "exec", "-i", cid, "python3", "-"],
            input=probe.read_text(encoding="utf-8"), text=True,
            capture_output=True, timeout=30,
        )
        assert "ISOLATION_PASS" in result.stdout, result.stdout + result.stderr
