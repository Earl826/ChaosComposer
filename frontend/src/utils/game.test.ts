import { describe, expect, it } from 'vitest'
import { canStartGame } from './game'

describe('musicGame room validation', () => {
  it('allows between 4 and 6 players', () => {
    expect(canStartGame(4)).toBe(true)
    expect(canStartGame(5)).toBe(true)
    expect(canStartGame(6)).toBe(true)
  })

  it('rejects invalid player counts', () => {
    expect(canStartGame(3)).toBe(false)
    expect(canStartGame(7)).toBe(false)
    expect(canStartGame(4.5)).toBe(false)
  })
})
