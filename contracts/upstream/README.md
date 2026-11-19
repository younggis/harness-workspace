# Locked upstream contract samples

These files are **real** observations from the running `dsh-v0.2.2-rc.4` stack,
sanitized (cookies/tickets/tokens/UUIDs/paths replaced). They are the gate for
upgrading dsh: a candidate image must satisfy `tests/test_upstream_contracts.py`
before its version is registered as a new template.

| File | Source | What it pins |
|---|---|---|
| `web-http.sanitized.json` | `scripts/capture_contracts.py` | root token→cookie exchange (303, `./`), root HTML content-type |
| `events-sse.sanitized.json` | same | `/plugins/events` is a long-lived SSE stream (no early frames captured) |
| `web-ws.sanitized.json` | same | `/api/remote.mux` accepts text frames after cookie+Host handshake |
| `session-contract.sanitized.json` | `scripts/capture_session_contract.py` | session projection rows: `modelSelection`, `permissions`, `tokenUsage`, `turnBoundary`, `sessionStats`, `turnOutline`, `userQuestions`, `agentPreset` |

Facts verified from upstream docs at the locked tag (not invented RPC names):

- `dsh --profile web --no-open --public-url <url> --trusted-host <host>`, default port **3080**.
- `--patch` is a launcher flag (before `--profile`), not an app flag.
- The mount root exchanges the launch token for a host-only signed cookie (303).
- Native WS `/api/remote.mux` requires **text** frames and the injected cookie.
- `/plugins/events` is SSE; it must not be buffered by the gateway.
- Model route config lives in `llm-pi-ai.providers` of the profile patch; protocol `openai-completions`.

Re-capture after an upstream upgrade, then run `./scripts/upgrade-check.ps1 -Version <new>`.
If a contract assertion fails, the adapter must be updated before the new template is published.
