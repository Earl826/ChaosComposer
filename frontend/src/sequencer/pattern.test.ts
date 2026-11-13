import { describe, expect, it } from 'vitest'
import backendExample from '../../../backend/schemas/sample_pattern.json?raw'
import { createPattern, INSTRUMENTS, parsePattern, serializePattern, toggleStep } from './pattern'

describe('pattern contract and editing', () => {
  it('loads and exports the backend fixture without adding tracks or changing notes', () => {
    expect(JSON.parse(serializePattern(parsePattern(backendExample)))).toEqual(JSON.parse(backendExample))
  })

  it('toggles only the requested note without mutating the prior version', () => {
    const original = createPattern()
    const edited = toggleStep(original, 'snare', 4)
    expect(original.tracks.every((track) => track.steps.every((step) => !step))).toBe(true)
    expect(edited.tracks.flatMap((track) => track.steps).filter(Boolean)).toHaveLength(1)
    expect(edited.tracks.find((track) => track.instrument === 'snare')?.steps[4]).toBe(true)
    expect(toggleStep(edited, 'snare', 4)).toEqual(original)
  })

  it('round-trips all supported instruments and a fractional tempo', () => {
    const pattern = createPattern()
    pattern.tempo = 123.5
    pattern.tracks.forEach((track, index) => { track.steps[index] = true })
    expect(pattern.tracks.map((track) => track.instrument)).toEqual(Object.keys(INSTRUMENTS))
    expect(parsePattern(serializePattern(pattern))).toEqual(pattern)
  })

  it('accepts backend defaults and case-insensitive instrument IDs', () => {
    const pattern = JSON.parse(backendExample)
    delete pattern.schema_version
    delete pattern.step_count
    pattern.tracks[0].instrument = ' KICK '
    expect(parsePattern(JSON.stringify(pattern))).toEqual(JSON.parse(backendExample))
  })

  it.each([null, [], 'invalid', {}, { ...createPattern(), unexpected: true },
    { ...createPattern(), schema_version: '2.0' }, { ...createPattern(), step_count: 32 },
    { ...createPattern(), tempo: '120' }, { ...createPattern(), tempo: 29 },
    { ...createPattern(), tempo: 301 }, { ...createPattern(), tracks: [] },
  ])('rejects invalid pattern data %j', (value) => {
    expect(() => parsePattern(JSON.stringify(value))).toThrow()
  })

  it('rejects invalid JSON', () => {
    expect(() => parsePattern('{broken')).toThrow('not valid JSON')
  })

  it.each(['unknown', '__proto__', 'constructor'])('rejects an unsupported instrument %s', (instrument) => {
    const pattern = createPattern()
    expect(() => parsePattern(JSON.stringify({ ...pattern, tracks: [{ ...pattern.tracks[0], instrument }] }))).toThrow('Unsupported instrument')
  })

  it('rejects duplicates after normalizing IDs, as the backend does', () => {
    const pattern = createPattern()
    const track = pattern.tracks[0]
    expect(() => parsePattern(JSON.stringify({ ...pattern, tracks: [track, { ...track, instrument: ' KICK ' }] }))).toThrow('Duplicate instrument')
  })

  it.each([Array(15).fill(false), Array(17).fill(false), Array(16).fill('false'), Array(16).fill(0)])(
    'rejects invalid step arrays %j', (steps) => {
      expect(() => parsePattern(JSON.stringify({ ...createPattern(), tracks: [{ instrument: 'kick', steps }] }))).toThrow('16 true/false steps')
    },
  )

  it('rejects unknown track fields instead of losing them on export', () => {
    const track = { ...createPattern().tracks[0], notes: [60] }
    expect(() => parsePattern(JSON.stringify({ ...createPattern(), tracks: [track] }))).toThrow('unsupported fields')
  })
})
