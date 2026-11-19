"""Extract REAL sanitized session-contract rows from a dsh-home named volume."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

VOL = "harness-harness-local-dev-home-319fc425-cf45-4307-b4a9-b693fe67cad9"
OUT = Path("contracts/upstream/session-contract.sanitized.json")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
PATH_RE = re.compile(r"(?:/[^\s\"']+){2,}")


def sanitize(value):
    s = json.dumps(value, ensure_ascii=False)
    s = UUID_RE.sub("<uuid>", s)
    s = PATH_RE.sub("<path>", s)
    return json.loads(s)


def main() -> None:
    f = subprocess.check_output([
        'docker', 'run', '--rm', '-v', f'{VOL}:/data:ro', 'alpine', 'sh',
        '-c', 'ls -S /data/storages/session_projcache/sessions/*.json | head -1',
    ]).decode().strip()
    raw = subprocess.check_output(['docker', 'run', '--rm', '-v', f'{VOL}:/data:ro', 'alpine', 'cat', f])
    rows = json.loads(raw)["record"]["rows"]
    keys = [
        "modelSelection", "permissions", "tokenUsage", "turnBoundary",
        "sessionStats", "turnOutline", "userQuestions", "agentPreset",
    ]
    OUT.write_text(json.dumps({
        "captured": True,
        "source": "dsh v0.2.2-rc.4 session_projcache (real, sanitized)",
        "rows": {k: sanitize(rows.get(k)) for k in keys if k in rows},
        "observed_rows": sorted(rows.keys()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
