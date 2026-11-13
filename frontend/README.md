# ChaosComposer beat sequencer

Person 6's standalone React prototype runs at the frontend's main URL.

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
