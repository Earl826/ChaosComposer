
import './App.css'
import BeatSequencer from './sequencer/BeatSequencer'

function App() {
  return (
    <main className="container">
      <header className="app-header">
        <a href="./" className="brand">ChaosComposer</a>
        <span>Beat studio</span>
      </header>
      <BeatSequencer />
    </main>
  )
}

export default App
