import { useEffect, useRef, useState } from 'react'
import BeatSequencer from '../sequencer/BeatSequencer'
import { createPattern, parsePattern } from '../sequencer/pattern'
import type { MusicalPattern } from '../sequencer/pattern'
import { GameApi, GameApiError } from './api'
import type { Assignment, PatternSubmission, PlayerSession, SessionState } from './api'

interface MusicEditorProps {
  session: PlayerSession
  apiBaseUrl?: string
}

// The lobby can mount this page directly with the credentials returned by create/join.
export default function MusicEditor({ session, apiBaseUrl }: MusicEditorProps) {
  const [room, setRoom] = useState<SessionState | null>(null)
  const [assignment, setAssignment] = useState<Assignment | null>(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const api = new GameApi(session, apiBaseUrl)
    let timer: ReturnType<typeof setTimeout>
    async function sync() {
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(10000)])
        const state = await api.getSession(signal)
        if (controller.signal.aborted) return
        setRoom((previous) => !previous || state.state_version >= previous.state_version ? state : previous)
        if (state.status === 'composing' && !state.submitted_player_ids.includes(session.player_id)) {
          const incoming = await api.getAssignment(signal)
          if (controller.signal.aborted) return
          if (incoming.round === state.current_round) {
            setAssignment((previous) => previous?.round === incoming.round && previous.chain_id === incoming.chain_id
              ? previous : incoming)
          }
        }
        setError('')
      } catch (cause) {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : 'Unable to connect to the game.')
        // Authentication and unimplemented endpoints need action before another attempt.
        if (cause instanceof GameApiError && [401, 403, 404, 501].includes(cause.status)) return
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void sync(), 2000)
    }
    void sync()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [session, apiBaseUrl, refresh])

  const submitted = room?.submitted_player_ids.includes(session.player_id)
  const currentAssignment = room?.status === 'composing' && assignment?.round === room.current_round ? assignment : null

  return (
    <div className="music-editor">
      <section className="round-status" aria-label="Game progress">
        <strong>Room {session.session_code}</strong>
        {room && <span>Round {room.current_round} of {room.total_rounds}</span>}
        {room?.status === 'composing' && <span>{room.submitted_player_ids.length} of {room.players.length} submitted</span>}
      </section>
      {error && <div className="connection-error" role="alert">
        <p>{error}</p>
        <button onClick={() => setRefresh((value) => value + 1)}>Retry connection</button>
      </div>}
      {!room && <p role="status">Connecting to your room…</p>}
      {room?.status === 'lobby' && <p role="status">Waiting for the host to start the game.</p>}
      {room?.status === 'prompt_submission' && <p role="status">Waiting for all players to submit their starting prompts.</p>}
      {room?.status === 'transitioning' && <p role="status">Preparing the next round…</p>}
      {room?.status === 'finished' && <p role="status">All rounds complete. Your music is ready for the final reveal.</p>}
      {room?.status === 'composing' && submitted && <p role="status">Pattern submitted. Waiting for the other players.</p>}
      {room?.status === 'composing' && !submitted && !currentAssignment && <p role="status">Loading your musical assignment…</p>}
      {currentAssignment && !submitted && <RoundEditor
        key={`${session.session_code}:${session.player_id}:${currentAssignment.round}:${currentAssignment.chain_id}`}
        session={session} apiBaseUrl={apiBaseUrl} assignment={currentAssignment}
        connectionError={Boolean(error)} onSubmitted={() => setRefresh((value) => value + 1)}
      />}
    </div>
  )
}

function RoundEditor({ session, apiBaseUrl, assignment, connectionError, onSubmitted }: MusicEditorProps & {
  assignment: Assignment
  connectionError: boolean
  onSubmitted: () => void
}) {
  const storageKey = `chaoscomposer.submission:${session.session_code}:${session.player_id}:${assignment.round}:${assignment.chain_id}`
  const [attempt, setAttempt] = useState<PatternSubmission | null>(() => {
    try {
      const saved = sessionStorage.getItem(storageKey)
      if (!saved) return null
      const value = JSON.parse(saved) as PatternSubmission
      if (value.chain_id !== assignment.chain_id || value.expected_round !== assignment.round ||
          typeof value.submission_id !== 'string' || !value.submission_id) return null
      return { ...value, pattern: parsePattern(JSON.stringify(value.pattern)) }
    } catch { return null }
  })
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const [pattern, setPattern] = useState<MusicalPattern>(() => attempt?.pattern ??
    (assignment.kind === 'pattern' ? assignment.pattern : createPattern()))

  useEffect(() => () => request.current?.abort(), [])

  async function submit() {
    if (request.current || accepted) return
    const submission = attempt ?? {
      chain_id: assignment.chain_id,
      expected_round: assignment.round,
      submission_id: crypto.randomUUID(),
      pattern,
    }
    try {
      // Persist before sending so a reload or uncertain response retries the same payload.
      sessionStorage.setItem(storageKey, JSON.stringify(submission))
    } catch {
      setError('Browser session storage is unavailable. Enable it before submitting. You can export your pattern for safekeeping.')
      return
    }
    setAttempt(submission)
    setBusy(true)
    setError('')
    const controller = new AbortController()
    request.current = controller
    try {
      await new GameApi(session, apiBaseUrl).submitPattern(submission,
        AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]))
      if (controller.signal.aborted) return
      setAccepted(true)
      onSubmitted()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof GameApiError && [422, 501].includes(cause.status)) {
        sessionStorage.removeItem(storageKey)
        setAttempt(null)
      }
      setError(cause instanceof Error ? cause.message : 'Submission failed. Retry to check or save this same pattern.')
    } finally {
      if (!controller.signal.aborted) {
        request.current = null
        setBusy(false)
      }
    }
  }

  return (
    <>
      <section className="assignment" aria-label="Your assignment">
        <h1>{assignment.kind === 'prompt' ? 'Compose the prompt' : 'Remix the incoming beat'}</h1>
        {assignment.kind === 'prompt' ? <p className="assigned-prompt">{assignment.prompt}</p>
          : <p>Listen to the previous player’s pattern, then change the notes and instruments to make your version.</p>}
      </section>
      <BeatSequencer initialPattern={pattern} locked={Boolean(attempt) || accepted}
        onPatternChange={setPattern}
        onSubmit={() => void submit()} submitDisabled={connectionError || busy || accepted}
        submitLabel={busy ? 'Submitting…' : accepted ? 'Submitted' : attempt ? 'Retry submission' : 'Submit pattern'} />
      {error && <p className="error" role="alert">{error}</p>}
      {(accepted || attempt) && <p role="status">{accepted
        ? 'Pattern saved. Waiting for the room to advance.'
        : 'This pattern is held for submission. Retry sends the same version to prevent duplicates.'}</p>}
    </>
  )
}
