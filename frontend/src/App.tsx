
import './App.css'
import { useState } from 'react'
import BeatSequencer from './sequencer/BeatSequencer'
import MusicEditor from './game/MusicEditor'
import type { PlayerSession } from './game/api'

function App() {
  const [live, setLive] = useState(false)
  const [session, setSession] = useState<PlayerSession | null>(null)
  return (
    <main className="container">
      <header className="app-header">
        <a href="./" className="brand">ChaosComposer</a>
        <button onClick={() => { setLive(!live); setSession(null) }}>
          {live ? 'Standalone studio' : 'Open game editor'}
        </button>
      </header>
      {!live && <BeatSequencer />}
      {live && !session && <section className="sequencer">
        <h1>Connect to your game</h1>
        <p>Use the player credentials returned when you create or join a room.</p>
        <form className="connect-form" onSubmit={(event) => {
          event.preventDefault()
          const data = new FormData(event.currentTarget)
          setSession({
            session_code: String(data.get('room')).trim().toUpperCase(),
            player_id: String(data.get('player')).trim(),
            player_token: String(data.get('token')).trim(),
          })
        }}>
          <label>Room code<input name="room" required minLength={4} maxLength={4} pattern="[A-Za-z0-9]{4}" autoComplete="off" /></label>
          <label>Player ID<input name="player" required pattern=".*\S.*" autoComplete="off" /></label>
          <label>Player token<input name="token" type="password" required pattern=".*\S.*" autoComplete="off" /></label>
          <button className="primary" type="submit">Connect</button>
        </form>
      </section>}
      {live && session && <MusicEditor session={session} />}
    </main>
  )
}

export default App
