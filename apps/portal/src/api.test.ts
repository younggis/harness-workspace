import { describe, it, expect, vi } from 'vitest'
import { newId } from './api'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

describe('newId', () => {
  it('returns a UUID v4 using crypto.randomUUID when available', () => {
    const g: any = globalThis
    const orig = g.crypto
    Object.defineProperty(g, 'crypto', {
      value: { randomUUID: () => 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee' },
      configurable: true,
    })
    expect(newId()).toBe('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')
    if (orig) Object.defineProperty(g, 'crypto', { value: orig, configurable: true })
  })

  it('falls back to getRandomValues when randomUUID is absent (plain HTTP host)', () => {
    const g: any = globalThis
    const orig = g.crypto
    let seed = 0
    Object.defineProperty(g, 'crypto', {
      value: { getRandomValues: (a: Uint8Array) => { a.fill(seed++); return a } },
      configurable: true,
    })
    const id = newId()
    expect(UUID_V4.test(id)).toBe(true)
    expect(newId()).not.toBe(id)
    if (orig) Object.defineProperty(g, 'crypto', { value: orig, configurable: true })
  })
})
