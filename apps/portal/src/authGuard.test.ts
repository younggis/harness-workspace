import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./api', () => ({ api: vi.fn() }))

import { api } from './api'
import { authGuard } from './authGuard'
import { me, authChecked } from './auth'

const route = (path: string, auth = false) => ({ path, meta: { auth } }) as any
const authed = { user: { login_norm: 'admin', is_platform_admin: true }, tenants: [], csrf_token: 'c' }

beforeEach(() => {
  vi.mocked(api).mockReset()
  me.value = null
  authChecked.value = false
})

describe('authGuard', () => {
  it('redirects a logged-out user away from a protected route', async () => {
    vi.mocked(api).mockRejectedValue(new Error('401'))
    expect(await authGuard(route('/', true))).toEqual({ path: '/login' })
    expect(await authGuard(route('/admin', true))).toEqual({ path: '/login' })
  })

  it('allows a logged-in user on a protected route', async () => {
    vi.mocked(api).mockResolvedValue(authed)
    expect(await authGuard(route('/', true))).toBe(true)
    expect(me.value.user.login_norm).toBe('admin')
  })

  it('sends a logged-in user away from the login page', async () => {
    vi.mocked(api).mockResolvedValue(authed)
    expect(await authGuard(route('/login'))).toEqual({ path: '/' })
  })

  it('keeps a logged-out user on the login page', async () => {
    vi.mocked(api).mockRejectedValue(new Error('401'))
    expect(await authGuard(route('/login'))).toBe(true)
  })
})
