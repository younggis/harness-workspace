# Locked upstream contract samples

Status: **PENDING_M0_E2E** — native dsh Web was not started in this session (no runtime
image built and the supplied DeepSeek key returned 401), so no real event samples could
be captured. Do not fabricate event names. `upstream.lock.json` records the facts that
WERE verified from the repository at the locked tag.

When M0 E2E is available, place sanitized samples here:

| File | Content | Source |
|---|---|---|
| `web-http.sanitized.json` | root token→cookie exchange, one 302/303, static asset path | browser/network capture |
| `web-ws.sanitized.json` | upgrade request/response headers + first event names | WS capture |
| `tool-call.sanitized.json` | invocation id, chunked args, result correlation | session log |
| `approval.sanitized.json` | real approval prompt shape | session log |

Known from upstream docs at `dsh-v0.2.2-rc.4` (NOT invented RPC names):

- `dsh --profile web --no-open --public-url <url> --trusted-host <host>`, default port **3080**.
- Browser-facing external authority must be passed via `--trusted-host`; `Host` header is preserved by the proxy.
- The mount root alone exchanges the launch token for a host-only signed cookie; redirects 302/303.
- Config lives in the profile's `cordis.patch.yml`; protocol id for OpenAI Chat Completions is `openai-completions`.
- Model key is stored in `$DSH_HOME/.credentials.yaml`; settings keep only a credential reference.
