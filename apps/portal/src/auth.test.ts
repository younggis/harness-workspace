import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./api', () => ({ api: vi.fn() }))

import { api } from './api'
import { ensureMe, invalidateMe, me, loadMe } from './auth'

const fake = { user: { login_norm: 'a1' }, tenants: [], csrf_token: 'c' }

beforeEach(() => {
  vi.mocked(api).mockReset()
  vi.mocked(api).mockResolvedValue(fake)
  invalidateMe()
})

describe('auth cache', () => {
  it('resolves /api/me once across rapid navigations', async () => {
    await ensureMe()
    me.value = fake // simulate a concurrent guard reusing the same value
    await ensureMe()
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('refreshes after invalidateMe (logout)', async () => {
    await ensureMe()
    invalidateMe()
    await ensureMe()
    expect(api).toHaveBeenCalledTimes(2)
    expect(me.value.user.login_norm).toBe('a1')
  })

  it('loadMe always refreshes', async () => {
    await loadMe()
    await loadMe()
    expect(api).toHaveBeenCalledTimes(2)
  })
})
