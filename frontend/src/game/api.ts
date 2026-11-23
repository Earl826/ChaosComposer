import { parsePattern } from '../sequencer/pattern'
import type { MusicalPattern } from '../sequencer/pattern'

export interface PlayerSession {
  session_code: string
  player_id: string
  player_token: string
}

export interface SessionState {
  session_code: string
  status: 'lobby' | 'prompt_submission' | 'composing' | 'transitioning' | 'finished'
  state_version: number
  current_round: number
  total_rounds: number
  players: { player_id: string; name: string; is_host: boolean; is_ready: boolean }[]
  prompted_player_ids: string[]
  submitted_player_ids: string[]
}

export type Assignment = {
  kind: 'prompt'; chain_id: string; round: 1; prompt: string
} | {
  kind: 'pattern'; chain_id: string; round: number
  previous_version_id: string; pattern: MusicalPattern
}

export interface PatternSubmission {
  chain_id: string
  expected_round: number
  submission_id: string
  pattern: MusicalPattern
}

export class GameApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export class GameApi {
  private readonly session: PlayerSession
  private readonly baseUrl: string

  constructor(session: PlayerSession, baseUrl = import.meta.env.VITE_API_BASE_URL || '/api') {
    this.session = session
    this.baseUrl = baseUrl.replace(/\/$/, '')
  }

  private async request<T>(path: string, signal: AbortSignal, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(this.session.session_code)}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        'X-Player-Token': this.session.player_token,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      // Keep credentials on the configured API origin if it redirects.
      redirect: 'error',
    })
    if (!response.ok) {
      if (response.status === 501) {
        throw new GameApiError('The game API is not implemented yet. The backend team must enable this endpoint.', 501)
      }
      let detail = `Game request failed (${response.status}).`
      try {
        const error = await response.json()
        if (typeof error.detail === 'string') detail = error.detail
      } catch { /* An upstream service may return an HTML error page. */ }
      throw new GameApiError(detail, response.status)
    }
    return response.json()
  }

  getSession(signal: AbortSignal): Promise<SessionState> {
    return this.request('', signal)
  }

  async getAssignment(signal: AbortSignal): Promise<Assignment> {
    // Assignment has a different response shape from room state.
    const result = await this.request<{ assignment: Assignment }>('/assignment', signal)
    const assignment = result.assignment
    if (!assignment || typeof assignment.chain_id !== 'string' || !assignment.chain_id ||
        !Number.isInteger(assignment.round)) throw new Error('The API returned an invalid assignment.')
    if (assignment.kind === 'prompt' && assignment.round === 1 && typeof assignment.prompt === 'string') return assignment
    if (assignment.kind === 'pattern' && assignment.round >= 2 && typeof assignment.previous_version_id === 'string') {
      // Rebuild the response so hidden prompt fields can never enter the editor.
      return {
        kind: 'pattern', chain_id: assignment.chain_id, round: assignment.round,
        previous_version_id: assignment.previous_version_id,
        pattern: parsePattern(JSON.stringify(assignment.pattern)),
      }
    }
    throw new Error('The API returned an invalid assignment.')
  }

  submitPattern(submission: PatternSubmission, signal: AbortSignal): Promise<SessionState> {
    return this.request('/submissions', signal, submission)
  }
}
