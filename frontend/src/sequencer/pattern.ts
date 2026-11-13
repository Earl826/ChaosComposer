// Matches backend/models.py and the allow-list in backend/pattern_store.py.
export const INSTRUMENTS = {
  kick: 'Kick',
  snare: 'Snare',
  hihat: 'Hi-hat',
  clap: 'Clap',
  tom: 'Tom',
  bass: 'Bass',
  synth: 'Synth',
  piano: 'Piano',
} as const

export type Instrument = keyof typeof INSTRUMENTS

export interface MusicalPattern {
  schema_version: '1.0'
  tempo: number
  step_count: 16
  tracks: { instrument: Instrument; steps: boolean[] }[]
}

export const MIN_TEMPO = 30
export const MAX_TEMPO = 300
export const STEP_COUNT = 16

export function isValidTempo(tempo: number): boolean {
  return Number.isFinite(tempo) && tempo >= MIN_TEMPO && tempo <= MAX_TEMPO
}

export function createPattern(): MusicalPattern {
  return {
    schema_version: '1.0',
    tempo: 120,
    step_count: STEP_COUNT,
    tracks: (Object.keys(INSTRUMENTS) as Instrument[]).map((instrument) => ({
      instrument,
      steps: Array<boolean>(STEP_COUNT).fill(false),
    })),
  }
}

export function toggleStep(pattern: MusicalPattern, instrument: Instrument, step: number): MusicalPattern {
  return {
    ...pattern,
    tracks: pattern.tracks.map((track) => track.instrument === instrument
      ? { ...track, steps: track.steps.map((active, index) => index === step ? !active : active) }
      : track),
  }
}

function checkedObject(value: unknown, keys: string[], label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`)
  }
  if (Object.keys(value).some((key) => !keys.includes(key))) {
    throw new Error(`${label} contains unsupported fields.`)
  }
  return value as Record<string, unknown>
}

export function parsePattern(json: string): MusicalPattern {
  let parsed: unknown
  try {
    parsed = JSON.parse(json)
  } catch {
    throw new Error('This file is not valid JSON.')
  }
  const value = checkedObject(parsed, ['schema_version', 'tempo', 'step_count', 'tracks'], 'Pattern')
  // These two fields also have defaults in the backend model.
  if (value.schema_version !== undefined && value.schema_version !== '1.0') {
    throw new Error('Only pattern schema 1.0 is supported.')
  }
  if (value.step_count !== undefined && value.step_count !== STEP_COUNT) {
    throw new Error('Patterns must have exactly 16 steps.')
  }
  if (typeof value.tempo !== 'number' || !isValidTempo(value.tempo)) {
    throw new Error('Tempo must be a number between 30 and 300 BPM.')
  }
  if (!Array.isArray(value.tracks) || value.tracks.length < 1 || value.tracks.length > 16) {
    throw new Error('A pattern must contain between 1 and 16 tracks.')
  }

  const seen = new Set<string>()
  const tracks = value.tracks.map((item, index) => {
    const track = checkedObject(item, ['instrument', 'steps'], `Track ${index + 1}`)
    if (typeof track.instrument !== 'string') {
      throw new Error(`Track ${index + 1} needs an instrument ID.`)
    }
    const instrument = track.instrument.trim().toLowerCase()
    if (!Object.hasOwn(INSTRUMENTS, instrument)) {
      throw new Error(`Unsupported instrument "${track.instrument}".`)
    }
    if (seen.has(instrument)) {
      throw new Error(`Duplicate instrument "${instrument}".`)
    }
    seen.add(instrument)
    if (!Array.isArray(track.steps) || track.steps.length !== STEP_COUNT ||
        track.steps.some((step) => typeof step !== 'boolean')) {
      throw new Error(`Track ${index + 1} needs exactly 16 true/false steps.`)
    }
    return { instrument: instrument as Instrument, steps: [...track.steps] as boolean[] }
  })
  return { schema_version: '1.0', tempo: value.tempo, step_count: STEP_COUNT, tracks }
}

export function serializePattern(pattern: MusicalPattern): string {
  return JSON.stringify(pattern, null, 2)
}
