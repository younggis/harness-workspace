// crypto.randomUUID() is only available in secure contexts (HTTPS / localhost).
// The dev portal is served over plain HTTP on a nip.io host, so fall back to a
// UUID v4 built from getRandomValues (available in non-secure contexts).
export function newId(): string {
  const c: any = typeof crypto !== 'undefined' ? crypto : null
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes)
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

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
