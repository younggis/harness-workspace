import type { RouteLocationNormalized } from 'vue-router'
import { ensureMe, me } from './auth'

// Enforces route meta.auth. Keeping this in its own module makes the
// logged-out navigation behavior unit-testable without mounting components.
export async function authGuard(to: RouteLocationNormalized) {
  if (to.meta.auth) {
    await ensureMe()
    if (!me.value) return { path: '/login' }
  } else if (to.path === '/login') {
    await ensureMe()
    if (me.value) return { path: '/' }
  }
  return true
}
