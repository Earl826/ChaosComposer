import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SequencerPlayer } from './audio'
import { createPattern, toggleStep } from './pattern'

function audioParam() {
  return {
    value: 0,
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    exponentialRampToValueAtTime: vi.fn(),
  }
}

function sourceNode() {
  return {
    connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(),
    frequency: audioParam(), onended: null,
  }
}

class FakeContext {
  static latest: FakeContext
  state = 'running'
  sampleRate = 1000
  destination = {}
  onstatechange: (() => void) | null = null
  sources: ReturnType<typeof sourceNode>[] = []
  resume = vi.fn(async () => {})
  close = vi.fn(async () => {})

  constructor() { FakeContext.latest = this }
  get currentTime() { return Date.now() / 1000 }
  createBuffer() { return { getChannelData: () => new Float32Array(1000) } }
  createGain() { return { connect: vi.fn(), disconnect: vi.fn(), gain: audioParam() } }
  createBiquadFilter() { return { connect: vi.fn(), disconnect: vi.fn(), frequency: audioParam() } }
  createOscillator() {
    const source = sourceNode()
    this.sources.push(source)
    return source
  }
  createBufferSource() { return this.createOscillator() }
}

describe('audio scheduling and lifecycle', () => {
  let player: SequencerPlayer
  let onStep = vi.fn<(step: number | null) => void>()
  let onStop = vi.fn<() => void>()

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(0)
    vi.stubGlobal('AudioContext', FakeContext)
    onStep = vi.fn<(step: number | null) => void>()
    onStop = vi.fn<() => void>()
    player = new SequencerPlayer(onStep, onStop)
  })

  afterEach(() => {
    player.dispose()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('schedules sixteenth notes against the audio clock and loops after 16 steps', async () => {
    const pattern = toggleStep(toggleStep(createPattern(), 'kick', 0), 'kick', 4)
    await player.start(pattern)
    vi.advanceTimersByTime(2050)
    const times = FakeContext.latest.sources.map((source) => source.start.mock.calls[0][0])
    expect(times).toEqual([0.03, 0.53, 2.0300000000000002])
    expect(onStep.mock.calls.filter(([step]) => step !== null).map(([step]) => step)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 0,
    ])
  })

  it('applies edits and tempo changes to upcoming steps without restarting', async () => {
    let pattern = toggleStep(createPattern(), 'kick', 0)
    await player.start(pattern)
    pattern = toggleStep({ ...pattern, tempo: 240 }, 'snare', 1)
    player.updatePattern(pattern)
    vi.advanceTimersByTime(250)
    const times = FakeContext.latest.sources.map((source) => source.start.mock.calls[0][0])
    expect(times).toEqual([0.03, 0.155, 0.155])
    expect(onStep).toHaveBeenLastCalledWith(2)
  })

  it('cancels queued voices, removes timers and restarts from step 1', async () => {
    const pattern = toggleStep(createPattern(), 'kick', 0)
    await player.start(pattern)
    const first = FakeContext.latest.sources[0]
    player.stop()
    expect(first.stop).toHaveBeenLastCalledWith()
    expect(first.disconnect).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    expect(onStep).toHaveBeenLastCalledWith(null)
    await player.start(pattern)
    vi.advanceTimersByTime(50)
    expect(onStep).toHaveBeenLastCalledWith(0)
    expect(vi.getTimerCount()).toBe(1)
  })

  it('does not restart after Stop while audio permission is pending', async () => {
    await player.start(createPattern())
    let resume!: () => void
    FakeContext.latest.resume.mockImplementationOnce(() => new Promise<void>((resolve) => { resume = resolve }))
    const startup = player.start(toggleStep(createPattern(), 'kick', 0))
    player.stop()
    resume()
    expect(await startup).toBe(false)
    expect(FakeContext.latest.sources).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps note edits made while audio is resuming', async () => {
    await player.start(createPattern())
    let resume!: () => void
    FakeContext.latest.resume.mockImplementationOnce(() => new Promise<void>((resolve) => { resume = resolve }))
    const startup = player.start(createPattern())
    player.updatePattern(toggleStep(createPattern(), 'kick', 0))
    resume()
    expect(await startup).toBe(true)
    expect(FakeContext.latest.sources).toHaveLength(1)
  })

  it('skips missed time instead of playing a burst of overdue notes', async () => {
    const pattern = createPattern()
    pattern.tracks[0].steps.fill(true)
    await player.start(pattern)
    vi.setSystemTime(10000)
    vi.advanceTimersByTime(25)
    expect(FakeContext.latest.sources).toHaveLength(2)
    expect(FakeContext.latest.sources[1].start.mock.calls[0][0]).toBeCloseTo(10.055)
  })

  it('stops on browser audio interruption and closes on disposal', async () => {
    await player.start(createPattern())
    const context = FakeContext.latest
    context.state = 'suspended'
    context.onstatechange?.()
    expect(onStop).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    player.dispose()
    expect(context.close).toHaveBeenCalledOnce()
  })
})
