import type { Instrument, MusicalPattern } from './pattern'
import { STEP_COUNT } from './pattern'

// Each hit owns its nodes so Stop also cancels sounds already scheduled ahead.
export function scheduleInstrument(
  context: BaseAudioContext,
  output: AudioNode,
  noise: AudioBuffer,
  instrument: Instrument,
  time: number,
): () => void {
  const voices: { source: AudioScheduledSourceNode; nodes: AudioNode[] }[] = []

  function envelope(source: AudioScheduledSourceNode, nodes: AudioNode[], duration: number, level: number, start: number) {
    const gain = context.createGain()
    gain.gain.setValueAtTime(0, start)
    gain.gain.linearRampToValueAtTime(level, start + 0.003)
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration)
    nodes[nodes.length - 1].connect(gain)
    gain.connect(output)
    const voice = { source, nodes: [...nodes, gain] }
    voices.push(voice)
    source.onended = () => voice.nodes.forEach((node) => node.disconnect())
    source.start(start)
    source.stop(start + duration)
  }

  function tone(frequency: number, endFrequency: number, duration: number, type: OscillatorType, level = 0.3) {
    const oscillator = context.createOscillator()
    oscillator.type = type
    oscillator.frequency.setValueAtTime(frequency, time)
    oscillator.frequency.exponentialRampToValueAtTime(endFrequency, time + duration)
    envelope(oscillator, [oscillator], duration, level, time)
  }

  function hiss(frequency: number, duration: number, type: BiquadFilterType, start = time) {
    const source = context.createBufferSource()
    source.buffer = noise
    const filter = context.createBiquadFilter()
    filter.type = type
    filter.frequency.value = frequency
    source.connect(filter)
    envelope(source, [source, filter], duration, 0.22, start)
  }

  switch (instrument) {
    case 'kick': tone(150, 45, 0.35, 'sine'); break
    case 'snare':
      hiss(1200, 0.16, 'highpass')
      tone(180, 100, 0.1, 'triangle', 0.1)
      break
    case 'hihat': hiss(7000, 0.06, 'highpass'); break
    case 'clap':
      for (const offset of [0, 0.012, 0.024]) hiss(1500, 0.07, 'bandpass', time + offset)
      break
    case 'tom': tone(220, 80, 0.25, 'sine'); break
    case 'bass': tone(65.41, 65.41, 0.3, 'triangle', 0.2); break
    case 'synth': tone(261.63, 261.63, 0.2, 'sawtooth', 0.12); break
    case 'piano':
      tone(261.63, 261.63, 0.6, 'sine', 0.22)
      tone(523.25, 523.25, 0.3, 'sine', 0.06)
      break
  }
  return () => voices.forEach(({ source, nodes }) => {
    source.stop()
    nodes.forEach((node) => node.disconnect())
  })
}

export class SequencerPlayer {
  private context: AudioContext | null = null
  private noise: AudioBuffer | null = null
  private output: GainNode | null = null
  private timer: ReturnType<typeof setInterval> | null = null
  private generation = 0
  private pattern: MusicalPattern | null = null
  private nextStep = 0
  private nextTime = 0
  private queuedSteps: { step: number; time: number }[] = []
  private hits: { endTime: number; cancel: () => void }[] = []
  private onStep: (step: number | null) => void
  private onStop: () => void

  constructor(onStep: (step: number | null) => void, onStop: () => void) {
    this.onStep = onStep
    this.onStop = onStop
  }

  updatePattern(pattern: MusicalPattern) {
    this.pattern = pattern
  }

  async start(pattern: MusicalPattern): Promise<boolean> {
    this.stop()
    const generation = this.generation
    this.pattern = pattern
    try {
      if (!this.context) {
        this.context = new AudioContext()
        this.noise = this.context.createBuffer(1, this.context.sampleRate, this.context.sampleRate)
        const samples = this.noise.getChannelData(0)
        for (let index = 0; index < samples.length; index++) samples[index] = Math.random() * 2 - 1
        this.context.onstatechange = () => {
          if (this.context?.state !== 'running') this.stop()
        }
      }
      await this.context.resume()
      if (generation !== this.generation) return false
      if (this.context.state !== 'running') throw new Error('The browser could not start audio. Try Play again.')
      this.output = this.context.createGain()
      this.output.gain.value = 0.45
      this.output.connect(this.context.destination)
      this.nextTime = this.context.currentTime + 0.03
      this.tick()
      this.timer = setInterval(() => this.tick(), 25)
      return true
    } catch (error) {
      if (generation !== this.generation) return false
      this.stop()
      throw error
    }
  }

  private tick() {
    if (!this.context || !this.output || !this.noise || !this.pattern) return
    const now = this.context.currentTime
    // Avoid a burst of old beats after a delayed timer or a sleeping device.
    if (this.nextTime < now) this.nextTime = now + 0.03
    while (this.nextTime < now + 0.1) {
      for (const track of this.pattern.tracks) {
        if (track.steps[this.nextStep]) {
          this.hits.push({
            endTime: this.nextTime + 0.65,
            cancel: scheduleInstrument(this.context, this.output, this.noise, track.instrument, this.nextTime),
          })
        }
      }
      this.queuedSteps.push({ step: this.nextStep, time: this.nextTime })
      this.nextTime += 60 / this.pattern.tempo / 4
      this.nextStep = (this.nextStep + 1) % STEP_COUNT
    }
    while (this.queuedSteps.length && this.queuedSteps[0].time <= now) {
      this.onStep(this.queuedSteps.shift()!.step)
    }
    this.hits = this.hits.filter((hit) => hit.endTime > now)
  }

  stop() {
    this.generation++
    if (this.timer !== null) clearInterval(this.timer)
    this.timer = null
    this.output?.disconnect()
    this.output = null
    this.hits.forEach((hit) => hit.cancel())
    this.hits = []
    this.queuedSteps = []
    this.nextStep = 0
    this.onStep(null)
    this.onStop()
  }

  dispose() {
    this.stop()
    if (this.context) {
      this.context.onstatechange = null
      void this.context.close().catch(() => {})
      this.context = null
    }
  }
}
