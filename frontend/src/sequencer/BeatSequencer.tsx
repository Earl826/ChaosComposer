import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { SequencerPlayer } from './audio'
import {
  createPattern, INSTRUMENTS, isValidTempo, MAX_TEMPO, MIN_TEMPO,
  parsePattern, serializePattern, STEP_COUNT, toggleStep,
} from './pattern'
import type { MusicalPattern } from './pattern'

const SAVE_KEY = 'chaoscomposer.pattern.v1'
const STEPS = Array.from({ length: STEP_COUNT }, (_, index) => index)

export default function BeatSequencer() {
  const [pattern, setPattern] = useState(createPattern)
  const [tempoDraft, setTempoDraft] = useState('120')
  const [playback, setPlayback] = useState<'stopped' | 'starting' | 'playing'>('stopped')
  const [activeStep, setActiveStep] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [importing, setImporting] = useState(false)
  const playerRef = useRef<SequencerPlayer | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const tempoInvalid = tempoDraft.trim() === '' || !isValidTempo(Number(tempoDraft))

  useEffect(() => {
    const player = new SequencerPlayer(setActiveStep, () => setPlayback('stopped'))
    playerRef.current = player
    const stopWhenHidden = () => {
      if (document.hidden) player.stop()
    }
    document.addEventListener('visibilitychange', stopWhenHidden)
    return () => {
      document.removeEventListener('visibilitychange', stopWhenHidden)
      player.dispose()
      playerRef.current = null
    }
  }, [])

  function updatePattern(next: MusicalPattern) {
    setPattern(next)
    playerRef.current?.updatePattern(next)
    setMessage('')
    setError('')
  }

  function loadPattern(json: string, success: string) {
    const next = parsePattern(json)
    playerRef.current?.stop()
    updatePattern(next)
    setTempoDraft(String(next.tempo))
    setMessage(success)
  }

  async function play() {
    const player = playerRef.current
    if (!player) return
    setError('')
    const startup = player.start(pattern)
    setPlayback('starting')
    try {
      if (await startup && playerRef.current === player) setPlayback('playing')
    } catch {
      setError('Audio could not start. Check your browser audio permissions, then try Play again.')
      setPlayback('stopped')
    }
  }

  function changeTempo(value: string) {
    setTempoDraft(value)
    if (value.trim() !== '' && isValidTempo(Number(value))) {
      updatePattern({ ...pattern, tempo: Number(value) })
    }
  }

  function save() {
    try {
      localStorage.setItem(SAVE_KEY, serializePattern(pattern))
      setError('')
      setMessage('Pattern saved in this browser.')
    } catch {
      setError('Browser storage is unavailable. Use Export JSON to save a file.')
    }
  }

  function reloadSaved() {
    try {
      const saved = localStorage.getItem(SAVE_KEY)
      if (saved === null) throw new Error('Save a pattern in this browser first.')
      loadPattern(saved, 'Saved pattern loaded.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The saved pattern could not be loaded.')
    }
  }

  function exportFile() {
    const blob = new Blob([serializePattern(pattern)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'chaoscomposer-pattern.json'
    link.click()
    // Give the browser time to start consuming the download.
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setError('')
    setMessage('Pattern exported as chaoscomposer-pattern.json.')
  }

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setImporting(true)
    setMessage('')
    try {
      if (file.size > 128 * 1024) throw new Error('Choose a pattern JSON file smaller than 128 KB.')
      loadPattern(await file.text(), `Loaded ${file.name}.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The file could not be read.')
    } finally {
      setImporting(false)
    }
  }

  return (
    <section className="sequencer" aria-labelledby="sequencer-title">
      <div className="sequencer-heading">
        <div>
          <h1 id="sequencer-title">Beat sequencer</h1>
        </div>
        <span className="loop-length">1 bar · 16 steps</span>
      </div>

      <div className="transport">
        <div className="playback-controls">
          <button className="primary" onClick={() => void play()}
            disabled={playback !== 'stopped' || importing || tempoInvalid}>
            {playback === 'starting' ? 'Starting…' : 'Play'}
          </button>
          <button onClick={() => playerRef.current?.stop()} disabled={playback === 'stopped'}>Stop</button>
        </div>
        <div className="tempo-control">
          <label htmlFor="tempo">Tempo <span>BPM</span></label>
          <input id="tempo" type="number" min={MIN_TEMPO} max={MAX_TEMPO} step="any"
            value={tempoDraft} disabled={importing} aria-invalid={tempoInvalid}
            aria-describedby="tempo-hint" onChange={(event) => changeTempo(event.target.value)}
            onBlur={() => setTempoDraft(String(pattern.tempo))} />
          <span id="tempo-hint">{tempoInvalid ? 'Enter 30–300 BPM' : '30–300 BPM'}</span>
        </div>
        <span className={`playback-state ${playback}`} role="status">
          {playback === 'playing' ? 'Playing' : playback === 'starting' ? 'Starting audio' : 'Stopped'}
        </span>
      </div>

      <div className="grid-scroll" tabIndex={0} role="region" aria-label="Beat grid, scroll horizontally on small screens">
        <table className="beat-grid">
          <caption>Toggle steps to add or remove a note. Each group of four steps is one beat.</caption>
          <thead><tr><th scope="col">Instrument</th>{STEPS.map((step) => (
            <th scope="col" key={step} className={activeStep === step ? 'current-step' : ''}>
              {step + 1}
            </th>
          ))}</tr></thead>
          <tbody>{pattern.tracks.map((track) => (
            <tr key={track.instrument}>
              <th scope="row">{INSTRUMENTS[track.instrument]}</th>
              {track.steps.map((active, step) => (
                <td key={step} className={activeStep === step ? 'current-step' : ''}>
                  <button type="button" className={`step ${active ? 'active' : ''} ${step % 4 === 0 ? 'beat-start' : ''}`}
                    aria-label={`${INSTRUMENTS[track.instrument]}, step ${step + 1}`}
                    aria-pressed={active} disabled={importing}
                    onClick={() => updatePattern(toggleStep(pattern, track.instrument, step))}>
                    <span aria-hidden="true">{active ? '●' : ''}</span>
                  </button>
                </td>
              ))}
            </tr>
          ))}</tbody>
        </table>
      </div>

      <div className="pattern-actions">
        <div className="file-controls">
          <button onClick={save} disabled={importing || tempoInvalid}>Save in browser</button>
          <button onClick={reloadSaved} disabled={importing}>Load saved</button>
          <button onClick={exportFile} disabled={importing || tempoInvalid}>Export JSON</button>
          <button onClick={() => fileRef.current?.click()} disabled={importing}>
            {importing ? 'Loading…' : 'Import JSON'}
          </button>
          <input ref={fileRef} type="file" accept=".json,application/json" hidden
            aria-label="Import pattern file" onChange={(event) => void importFile(event)} />
        </div>
        <button className="clear" disabled={importing} onClick={() => {
          playerRef.current?.stop()
          updatePattern({
            ...pattern,
            tracks: pattern.tracks.map((track) => ({
              ...track, steps: Array<boolean>(STEP_COUNT).fill(false),
            })),
          })
          setMessage('All steps cleared.')
        }}>Clear steps</button>
      </div>
      <div className="feedback">
        {error ? <p className="error" role="alert">{error}</p> : <p role="status">{message}</p>}
      </div>
      <p className="storage-hint">Save keeps one pattern on this device. Export a JSON file to keep more patterns or share a beat.</p>
    </section>
  )
}
