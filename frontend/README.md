# ChaosComposer beat sequencer

Person 6's standalone React prototype runs at the frontend's main URL.

## Phase 2 music editor

Select **Open game editor** to connect with a room code, player ID and player
token returned by the room create/join APIs. Credentials stay in React memory
and are sent in `X-Player-Token` headers. The connection form is a manual handoff
while the other team members build the room, lobby and prompt pages.

The lobby can mount the editor directly with its authenticated session:

```tsx
import MusicEditor from './game/MusicEditor'

<MusicEditor session={playerSession} />
```

`playerSession` contains `session_code`, `player_id` and `player_token`, using
the names from `backend/models.py`. Remount the page when changing players or
rooms. The default API prefix is `/api`. During `npm run dev`, Vite proxies that
prefix to `http://127.0.0.1:7071`. For a hosted backend, set
`VITE_API_BASE_URL=https://<function-app-host>/api` in `frontend/.env.local`
and restart Vite. The backend must allow the frontend origin and
`X-Player-Token`/`Content-Type` headers through CORS. Keep secrets out of Vite
environment variables, which are public browser configuration.

The editor calls the existing gameplay contracts:

| Request | Editor behaviour |
| --- | --- |
| `GET /api/sessions/{session_code}` | Refresh phase, current round and submission progress every two seconds |
| `GET /api/sessions/{session_code}/assignment` | Show the assigned prompt in round 1; load only the incoming pattern in rounds 2+ |
| `POST /api/sessions/{session_code}/submissions` | Send `chain_id`, `expected_round`, `submission_id` and the pattern JSON |

The backend owns automatic round advancement after all submissions persist.
The editor waits for that state change, loads the next assignment and resets
the grid. Repeated room updates preserve edits within the same assignment.
An incoming pattern with fewer tracks can gain instruments through **Add
instrument**. All eight preset sounds continue to use local Web Audio synthesis.

Before posting, the editor saves the exact submission in sessionStorage with a
unique ID. An uncertain result locks that version and offers **Retry submission**.
Retries, including after reloading and reconnecting with the same credentials
in the same tab, reuse the saved ID and payload. Validation rejection unlocks
editing. Tokens are excluded from the saved submission and pattern export.

**Backend dependency as of the Phase 2 implementation:** the cloned `main` at
`ef77f56` still returns HTTP 501 for all three gameplay routes above. Domain
rotation and pattern storage code exist, but the HTTP handlers still need
authentication and persistence wiring by their owners. The editor displays
the 501 error and offers an explicit retry. Live Cosmos DB, Azure hosting and
multi-browser game-cycle verification require those endpoints to be enabled.
SignalR broadcasts belong to Paul's task; this page currently refreshes state
through polling.

The React integration tests use mocked HTTP responses to verify prompt privacy,
incoming pattern editing, added instruments, round changes, progress, duplicate
protection, validation errors and network retry/reload behaviour. Audio tests
and pattern round-trip tests also run with `npm test`.

For the team integration check, open the hosted frontend in at least two
browsers with different players. Complete the prompt phase, then check each
editor's round-one prompt. Submit all players' patterns and verify that round
2 loads the saved incoming notes and tempo while hiding the original prompt.
Repeat through the final round and confirm the completed-game message. Test
an interrupted submission and retry with the same ID. These live checks remain
pending until the backend endpoints are available.

## Run and check

Use Node.js 22.12 or newer, then run these commands from `frontend`.

```sh
npm ci
npm run dev
```

Open the local URL printed by Vite. Toggle steps with a mouse, or focus a step
with Tab and use Space or Enter. Play loops the 16 steps as one bar of 4/4.
Stop cancels queued notes and the next Play starts from step 1. Tempo accepts
30–300 BPM, including fractional values. Edits affect upcoming audio within
the 100 ms scheduling window. Playback stops when the tab is hidden.

Save in browser stores one pattern using localStorage. Load saved restores it,
including after a page reload. Export JSON downloads `chaoscomposer-pattern.json`.
Import JSON validates a local file before replacing the current pattern. Clear
steps stops playback and clears the active grid. A saved pattern can be loaded
again after clearing.

```sh
npm test
npm run build
npm run lint
```

## Pattern contract

The implementation follows `backend/models.py`, the instrument allow-list in
`backend/pattern_store.py`, and `backend/schemas/sample_pattern.json`.

- `schema_version` is `"1.0"` and `step_count` is `16`. The importer accepts
  these fields being omitted, matching the backend defaults.
- `tempo` is a number from 30 to 300.
- `tracks` contains unique instrument IDs and 16 boolean `steps` per track.
- Supported IDs are `kick`, `snare`, `hihat`, `clap`, `tom`, `bass`, `synth`,
  and `piano`. Imports normalize case and surrounding whitespace as the backend
  validator does. Export writes the canonical lower-case IDs.
- Imported track order and subsets are preserved. Unknown fields and invalid
  data produce a visible error and leave the current pattern available.

All sounds are synthesized locally through Web Audio. Bass uses C2, and synth
and the piano-like voice use C4. The current step format has fixed pitches.
`BeatSequencer` owns the editing state, `pattern.ts` handles interchange, and
`SequencerPlayer` schedules audio. Playback creates/resumes AudioContext from
the Play gesture and releases audio resources on unmount.

The JSON contract is the integration point with Person 5. Confirm these
instrument IDs and fixed-pitch sounds with Earl when integrating with gameplay.

## Browser acceptance check

1. Activate Kick steps 1, 5, 9 and 13, and Snare steps 5 and 13. Toggle a note
   off and back on. Press Play and check the moving step marker and audible beat.
2. Change tempo while playing, then Stop and Play. Confirm the loop starts at 1.
3. Save in browser, clear the grid, and Load saved. Reload the page and load
   again. Check the notes and tempo.
4. Export JSON and reimport it. Import the backend sample file and confirm its
   three tracks, then try malformed JSON and check that the grid is preserved.
5. At a narrow viewport, scroll the grid sideways and use the controls. Switch
   tabs during playback and confirm that playback stops.

Vitest covers immutable note editing, backend fixture round-trips, malformed
imports, scheduling, live edits, tempo changes, cancellation during startup,
and audio cleanup. Browser playback requires an audio-capable browser and an
output device.
