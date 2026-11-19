"""RuntimeDriver contract and the Docker-backed implementation.

Only the worker holds the Engine socket. It accepts typed operations and fixed
resource templates; it never accepts image names, mount paths or Docker parameters
from the web tier. Volumes and networks are labelled with installation + workspace +
generation and are never taken over when labels conflict.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class SpaceSpec:
    workspace_id: str
    tenant_id: str
    generation: int
    installation_id: str
    image: str
    cpu: int
    memory_bytes: int
    pids_limit: int
    workspace_host: str


class RuntimeDriver:
    def ensure(self, spec: SpaceSpec) -> None: ...
    def start(self, spec: SpaceSpec) -> str: ...       # returns container id
    def stop(self, spec: SpaceSpec) -> None: ...
    def rebuild(self, old_spec: SpaceSpec, new_spec: SpaceSpec) -> str: ...
    def inspect(self, spec: SpaceSpec) -> dict: ...
    def attach_gateway(self, spec: SpaceSpec) -> None: ...
    def credential(self, spec: SpaceSpec) -> str: ...


class DockerRuntimeDriver(RuntimeDriver):
    def __init__(self, installation_id: str):
        import docker  # imported lazily so offline tests need no Docker SDK
        self.client = docker.from_env()
        self.installation_id = installation_id
        self._credentials: dict = {}

    def _labels(self, spec: SpaceSpec) -> dict:
        # Volumes and networks are reused across generations, so labels must
        # NOT include generation (otherwise rebuild hits LABEL_CONFLICT).
        return {
            "harness.installation": self.installation_id,
            "harness.workspace": spec.workspace_id,
            "harness.resource": "runtime",
        }

    def _names(self, spec: SpaceSpec) -> tuple[str, str, str, str]:
        g = spec.generation
        return (
            f"harness-{self.installation_id}-proj-{spec.workspace_id}",
            f"harness-{self.installation_id}-home-{spec.workspace_id}",
            f"harness-{self.installation_id}-net-{spec.workspace_id}-g{g}",
            f"harness-{self.installation_id}-rt-{spec.workspace_id}-g{g}",
        )

    def _volume(self, name: str, labels: dict):
        existing = next((v for v in self.client.volumes.list() if v.name == name), None)
        if existing:
            if not set(labels.items()).issubset(existing.attrs.get("Labels", {}).items()):
                raise RuntimeError(f"LABEL_CONFLICT: refusing to take over volume {name}")
            return existing
        return self.client.volumes.create(name=name, labels=labels, driver="local")

    def _network(self, name: str, labels: dict):
        existing = next((n for n in self.client.networks.list() if n.name == name), None)
        if existing:
            if not set(labels.items()).issubset(existing.attrs.get("Labels", {}).items()):
                raise RuntimeError(f"LABEL_CONFLICT: refusing to take over network {name}")
            return existing
        return self.client.networks.create(name=name, driver="bridge", internal=True, labels=labels)

    def ensure(self, spec: SpaceSpec) -> None:
        labels = self._labels(spec)
        proj, home, net, _ = self._names(spec)
        self._volume(proj, {**labels, "harness.resource": "project"})
        self._volume(home, {**labels, "harness.resource": "dsh-home"})
        self._network(net, labels)

    def _container_config(self, spec: SpaceSpec, proj: str, home: str, net: str, *, model_token: str = ""):
        labels = self._labels(spec)
        return dict(
            name=self._names(spec)[3],
            image=spec.image,
            labels=labels,
            detach=True,
            # attached explicitly below with the generation-scoped alias
            environment={
                "DSH_HOME": "/dsh-home",
                "DSH_PUBLIC_URL": f"http://{spec.workspace_host}/",
                "DSH_TRUSTED_HOST": spec.workspace_host,
                "HARNESS_WORKSPACE_ID": spec.workspace_id,
                "HARNESS_GENERATION": str(spec.generation),
                # dsh's native-addon loader copies .node files to /tmp before dlopen;
                # our hardened tmpfs is noexec. Load directly from the read-only image.
                "NARB_DISABLE_NATIVE_CACHE": "1",
                "HARNESS_MODEL_TOKEN": model_token,
            },
            volumes={proj: {"bind": "/workspace", "mode": "rw"},
                     home: {"bind": "/dsh-home", "mode": "rw"}},
            user="10001:10001",
            read_only=True,
            tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            nano_cpus=spec.cpu * 1_000_000_000,
            mem_limit=spec.memory_bytes,
            pids_limit=spec.pids_limit,
            command=["python3", "/opt/harness/entrypoint.py"],
        )

    def start(self, spec: SpaceSpec) -> str:
        # Clean any stale containers/networks from earlier generations first.
        self.stop(spec)
        self.ensure(spec)
        proj, home, net, name = self._names(spec)
        cfg = self._container_config(spec, proj, home, net, model_token=self.credential(spec))
        container = self.client.containers.run(**cfg)
        # Give the runtime a globally unique, generation-scoped alias on its space
        # network so relay can address it deterministically.
        alias = f"rt-{spec.workspace_id}-g{spec.generation}"
        self.client.networks.get(net).connect(container, aliases=[alias])
        return container.id

    def stop(self, spec: SpaceSpec) -> None:
        # Remove every container of this logical workspace (any stale generation).
        for c in self.client.containers.list(
            all=True, filters={"label": f"harness.workspace={spec.workspace_id}"},
        ):
            try:
                c.remove(force=True)
            except Exception:
                pass
        # Remove every space network by label, after detaching gateway services.
        for n in self.client.networks.list(
            filters={"label": f"harness.workspace={spec.workspace_id}"},
        ):
            for endpoint in list((n.attrs.get("Containers") or {}).keys()):
                try:
                    n.disconnect(endpoint, force=True)
                except Exception:
                    pass
            try:
                n.remove()
            except Exception:
                pass

    def rebuild(self, old_spec: SpaceSpec, new_spec: SpaceSpec) -> str:
        self.stop(old_spec)
        return self.start(new_spec)

    def inspect(self, spec: SpaceSpec) -> dict:
        name = self._names(spec)[3]
        c = next((x for x in self.client.containers.list(all=True) if x.name == name), None)
        if not c:
            return {"running": False}
        c.reload()
        return {"running": c.status == "running", "id": c.id, "status": c.status}

    def attach_gateway(self, spec: SpaceSpec) -> None:
        net_name = self._names(spec)[2]
        net = self.client.networks.get(net_name)
        # Locate by Compose service label, not a hard-coded container name.
        for service, alias in (("relay", "relay"), ("llm", "model-proxy")):
            try:
                matches = self.client.containers.list(filters={
                    "label": f"com.docker.compose.service={service}",
                })
                if not matches:
                    continue
                c = matches[0]
                already = {n for n in (c.attrs.get("NetworkSettings", {}).get("Networks", {}) or {})}
                if net_name in already:
                    continue
                net.connect(c, aliases=[alias])
            except Exception:
                pass  # service may not be up yet; reconcile retries

    def credential(self, spec: SpaceSpec) -> str:
        """Stable per (workspace, generation) token.

        Derived from a high-entropy seed so a worker restart never produces a
        token different from the one already injected into a live container.
        Rotating generation changes the token; old values are revoked explicitly.
        """
        seed = os.environ.get("HARNESS_WORKSPACE_TOKEN_SEED", "")
        key = (spec.workspace_id, spec.generation)
        if seed:
            mac = hmac.new(
                seed.encode("utf-8"),
                f"{spec.workspace_id}:{spec.generation}".encode("utf-8"),
                hashlib.sha256,
            ).digest()
            token = base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")
            self._credentials[key] = token
            return token
        if key not in self._credentials:
            self._credentials[key] = secrets.token_urlsafe(32)
        return self._credentials[key]
