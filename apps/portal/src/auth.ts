// Shared authentication state. The router guard and the app shell both use it,
// so a protected route can never render before /api/me has been resolved.
import { ref } from 'vue'
import { api } from './api'

export const me = ref<any>(null)
export const authChecked = ref(false)
let pending: Promise<any> | null = null

export async function loadMe() {
  try {
    me.value = await api('/api/me')
  } catch {
    me.value = null
  }
  authChecked.value = true
  return me.value
}

// Resolve /api/me at most once per navigation, even with concurrent guards.
export function ensureMe(): Promise<any> {
  if (pending) return pending
  pending = loadMe().finally(() => { pending = null })
  return pending
}
