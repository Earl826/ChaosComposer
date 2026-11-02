
import './App.css'

function App() {
  return (
    <main className="container">
      <h1>musicGame</h1>
      <p>A multiplayer musical Chinese Whispers game.</p>

      <section className="card">
        <h2>Welcome to musicGame!</h2>
        <p>Create or join a room to start making music.</p>

        <div className="buttons">
          <button disabled>Create Room</button>
          <button disabled>Join Room</button>
        </div>

      </section>
    </main>
  )
}

export default App
