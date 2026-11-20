// Shared authentication state. The router guard and the app shell both use it,
// so a protected route can never render before /api/me has been resolved.
import { ref } from 'vue'
import { api } from './api'

export const me = ref<any>(null)
export const authChecked = ref(false)
let pending: Promise<any> | null = null
let loadedAt = 0
const TTL_MS = 30_000

export async function loadMe() {
  try {
    me.value = await api('/api/me')
  } catch {
    me.value = null
  }
  authChecked.value = true
  loadedAt = Date.now()
  return me.value
}

// Avoid a /api/me round-trip on every navigation; 30s is short enough that
// server-side revocation is still reflected quickly on the next full load.
export function ensureMe(): Promise<any> {
  if (me.value && Date.now() - loadedAt < TTL_MS) return Promise.resolve(me.value)
  if (pending) return pending
  pending = loadMe().finally(() => { pending = null })
  return pending
}

// Call on logout / tenant switch so a stale cached identity is never restored.
export function invalidateMe() {
  me.value = null
  authChecked.value = false
  loadedAt = 0
  pending = null
}
