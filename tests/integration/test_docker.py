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
        mounts = [m["Name"] for m in cfg["Binds"]] if cfg.get("Binds") else []
        assert len(mounts) >= 2  # project + dsh-home named volumes
