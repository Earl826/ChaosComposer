// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MusicEditor from './MusicEditor'
import { createPattern } from '../sequencer/pattern'
import type { Assignment, PatternSubmission, SessionState } from './api'

vi.mock('../sequencer/audio', () => ({
  SequencerPlayer: class {
    updatePattern() {}
    stop() {}
    dispose() {}
  },
}))

const session = { session_code: 'BEAT', player_id: 'sam', player_token: 'private-token' }
let room: SessionState
let assignment: Assignment
let posts: PatternSubmission[]
let responseStatus: number
let loseResponse: boolean
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  room = {
    session_code: 'BEAT', status: 'composing', state_version: 4,
    current_round: 1, total_rounds: 4,
    players: ['sam', 'alex', 'jo', 'riley'].map((player_id) => ({ player_id, name: player_id, is_host: player_id === 'sam', is_ready: true })),
    submitted_player_ids: [], prompted_player_ids: ['sam', 'alex', 'jo', 'riley'],
  }
  assignment = { kind: 'prompt', chain_id: 'chain-a', round: 1, prompt: 'A robot in a haunted arcade' }
  posts = []
  responseStatus = 200
  loseResponse = false
  fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    expect(init?.headers).toMatchObject({ 'X-Player-Token': 'private-token' })
    const url = String(input)
    if (url.endsWith('/submissions')) {
      posts.push(JSON.parse(String(init?.body)))
      if (loseResponse) throw new TypeError('Connection lost')
      if (responseStatus !== 200) return new Response(JSON.stringify({ detail: 'Submission rejected' }), { status: responseStatus })
      room = { ...room, submitted_player_ids: ['sam'], state_version: room.state_version + 1 }
    }
    return new Response(JSON.stringify(url.endsWith('/assignment') ? { assignment } : room), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openEditor() {
  const view = render(<MusicEditor session={session} apiBaseUrl="https://game.example/api" />)
  await act(async () => {})
  await screen.findByRole('button', { name: 'Submit pattern' })
  return view
}

async function nextPoll() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 2100)) })
}

describe('music editor API integration', () => {
  it('shows the round-one prompt and posts the edited pattern using authenticated server assignment', async () => {
    await openEditor()
    expect(screen.getByText('A robot in a haunted arcade')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('Kick, step 1'))
    fireEvent.change(screen.getByLabelText('Tempo BPM'), { target: { value: '150' } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit pattern' }))
    await screen.findByText('Pattern submitted. Waiting for the other players.')
    expect(posts).toHaveLength(1)
    expect(posts[0]).toMatchObject({ chain_id: 'chain-a', expected_round: 1, pattern: { tempo: 150 } })
    expect(posts[0].pattern.tracks[0].steps[0]).toBe(true)
    expect(posts[0].submission_id).toBeTruthy()
    expect(JSON.stringify(posts[0])).not.toContain('private-token')
  })

  it('loads later-round notes and tempo, hides the original prompt and adds a missing instrument', async () => {
    room.current_round = 2
    const pattern = createPattern()
    pattern.tempo = 90
    pattern.tracks = [pattern.tracks[0]]
    pattern.tracks[0].steps[3] = true
    assignment = { kind: 'pattern', chain_id: 'chain-b', round: 2, previous_version_id: 'v1', pattern }
    // Even an accidental extra prompt field from the API must stay hidden.
    Object.assign(assignment, { prompt: 'Secret original prompt' })
    await openEditor()
    expect(screen.queryByText('Secret original prompt')).toBeNull()
    expect(screen.getByLabelText('Kick, step 4').getAttribute('aria-pressed')).toBe('true')
    expect((screen.getByLabelText('Tempo BPM') as HTMLInputElement).value).toBe('90')
    fireEvent.change(screen.getByLabelText('Add instrument'), { target: { value: 'bass' } })
    fireEvent.click(screen.getByLabelText('Bass, step 1'))
    fireEvent.click(screen.getByRole('button', { name: 'Submit pattern' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].pattern.tracks.map((track) => track.instrument)).toEqual(['kick', 'bass'])
    expect(posts[0].pattern.tracks[1].steps[0]).toBe(true)
  })

  it('preserves edits during polling and loads a fresh assignment when the round changes', async () => {
    await openEditor()
    fireEvent.click(screen.getByLabelText('Kick, step 1'))
    await nextPoll()
    expect(screen.getByLabelText('Kick, step 1').getAttribute('aria-pressed')).toBe('true')
    const pattern = createPattern()
    pattern.tempo = 85
    pattern.tracks[1].steps[7] = true
    room = { ...room, current_round: 2, state_version: 5 }
    assignment = { kind: 'pattern', chain_id: 'chain-b', round: 2, previous_version_id: 'v2', pattern }
    await nextPoll()
    expect(screen.queryByText('A robot in a haunted arcade')).toBeNull()
    expect(screen.getByLabelText('Kick, step 1').getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByLabelText('Snare, step 8').getAttribute('aria-pressed')).toBe('true')
    expect((screen.getByLabelText('Tempo BPM') as HTMLInputElement).value).toBe('85')
  })

  it('retries an identical submission after network failure and after reloading the editor', async () => {
    const view = await openEditor()
    loseResponse = true
    fireEvent.click(screen.getByLabelText('Kick, step 5'))
    fireEvent.click(screen.getByRole('button', { name: 'Submit pattern' }))
    await screen.findByText('Connection lost')
    expect((screen.getByLabelText('Kick, step 1') as HTMLButtonElement).disabled).toBe(true)
    view.unmount()
    render(<MusicEditor session={session} apiBaseUrl="https://game.example/api" />)
    await screen.findByRole('button', { name: 'Retry submission' })
    expect(screen.getByLabelText('Kick, step 5').getAttribute('aria-pressed')).toBe('true')
    loseResponse = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry submission' }))
    await screen.findByText('Pattern submitted. Waiting for the other players.')
    expect(posts).toHaveLength(2)
    expect(posts[1]).toEqual(posts[0])
  })

  it('unlocks a pattern rejected by validation so the player can correct and resubmit it', async () => {
    await openEditor()
    responseStatus = 422
    fireEvent.click(screen.getByRole('button', { name: 'Submit pattern' }))
    await screen.findByText('Submission rejected')
    expect((screen.getByLabelText('Kick, step 1') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByLabelText('Kick, step 1'))
    responseStatus = 200
    fireEvent.click(screen.getByRole('button', { name: 'Submit pattern' }))
    await screen.findByText('Pattern submitted. Waiting for the other players.')
    expect(posts[1].submission_id).not.toBe(posts[0].submission_id)
    expect(posts[1].pattern.tracks[0].steps[0]).toBe(true)
  })

  it('shows the backend 501 blocker and retries only when requested', async () => {
    fetchMock.mockImplementation(async () => new Response('{}', { status: 501 }))
    render(<MusicEditor session={session} apiBaseUrl="https://game.example/api" />)
    await screen.findByText(/The game API is not implemented yet/)
    await nextPoll()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }))
    await act(async () => {})
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('shows waiting and finished states and never offers an early client-side advance', async () => {
    room.submitted_player_ids = ['sam']
    render(<MusicEditor session={session} apiBaseUrl="https://game.example/api" />)
    await act(async () => {})
    await screen.findByText('Pattern submitted. Waiting for the other players.')
    room = { ...room, status: 'finished', state_version: 6 }
    await nextPoll()
    expect(screen.getByText(/All rounds complete/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Submit pattern' })).toBeNull()
    expect(fetchMock.mock.calls.every(([url]) => !String(url).endsWith('/advance'))).toBe(true)
  })
})
