// Same-origin calls: browser -> edge -> api. Cookies are host-only, HttpOnly.
// CSRF is double-submit: readable cookie + X-CSRF-Token header.
export function csrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)harness_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

export async function api(path: string, init: RequestInit = {}): Promise<any> {
  const method = (init.method || 'GET').toUpperCase()
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> || {}) }
  if (!['GET', 'HEAD'].includes(method)) headers['X-CSRF-Token'] = csrf()
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  if (!res.ok) {
    let msg = `${res.status}`
    try { msg = (await res.json()).error?.message || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  if (res.status === 204) return null
  return res.json()
}

export async function enterWorkspace(host: string, ticket: string, target: string) {
  const form = document.createElement('form')
  form.method = 'POST'
  form.action = `http://${host}/_platform/enter`
  const t = document.createElement('input')
  t.type = 'hidden'; t.name = 'ticket'; t.value = ticket
  form.appendChild(t)
  document.body.appendChild(form)
  form.submit() // cross-host form POST is the single intentional portal -> workspace write
  return target
}
