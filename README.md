<div align="center">

# 🎼 ChaosComposer

### Pass the music. Twist the melody. Reveal the chaos.

**A cloud-native multiplayer music game where every round transforms the song.**

![Project Status](https://img.shields.io/badge/Status-In%20Development-F59E0B?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Azure](https://img.shields.io/badge/Microsoft-Azure-0078D4?style=for-the-badge)
![React](https://img.shields.io/badge/React-TypeScript-149ECA?style=for-the-badge&logo=react&logoColor=white)

*University of Southampton · COMP3207 Cloud Application Development · Group T*

</div>

---

## The concept

**ChaosComposer** combines collaborative music creation with the unpredictability of a party game. Inspired by the passing-and-reinterpretation mechanics of *Gartic Phone*, it challenges groups of **4–6 players** to transform musical ideas across a sequence of rounds.

Each player begins with a prompt. Prompts become musical clips, clips move between players, and every new contributor reshapes what they hear, often without knowing the original inspiration. Players can compose with the built-in sequencer or record their own vocals, humming, beatboxing and other sounds using a microphone. Secret musical missions add an extra layer of creative disruption. The result is a collection of evolving compositions whose histories are revealed at the end of the game.

**The goal isn't a perfect song. It's discovering how far an idea can travel.**

## The experience

The envisioned full game brings together:

- **Private multiplayer rooms** with room codes, player presence and reconnectable sessions.
- **Simultaneous musical chains** so everyone creates, listens and contributes during each round.
- **An in-browser music studio** with a beat sequencer, melody editing, instrument sounds and immediate audio playback.
- **Microphone recording as an alternative to sequencing**, letting players sing, hum, beatbox or capture original audio directly in the browser.
- **Secret creative challenges** that influence how players reinterpret each composition.
- **Timed, server-coordinated rounds** with automatic chain rotation and live game-state updates.
- **Persistent composition histories** preserving each contribution and its place in the musical journey.
- **Cloud-backed audio contributions** using Azure Blob Storage for recordings, with playback and layering across successive musical versions.
- **A final reveal** featuring side-by-side progression, playback of each stage and community voting.

## Cloud-native by design

ChaosComposer is designed around a separation of responsibilities: **the browser handles responsive music creation and playback, while Azure coordinates the shared game**.

```text
                  ┌─────────────────────────────────┐
                  │     React + TypeScript          │
                  │     Browser music studio        │
                  │  Sequencer · Mic · Playback     │
                  └───────────────┬─────────────────┘
                                  │ HTTPS APIs
                                  ▼
                  ┌─────────────────────────────────┐
                  │        Azure Functions          │
                  │           Python 3.14           │
                  │    Game logic · Coordination    │
                  └───────┬─────────┬─────────┬─────┘
                          │         │         │
                 Game state│         │         │Audio assets
                          ▼         │         ▼
                  ┌──────────────┐  │  ┌─────────────────┐
                  │ Azure Cosmos │  │  │ Azure Blob      │
                  │ DB for NoSQL │  │  │ Storage         │
                  └──────────────┘  │  └─────────────────┘
                                    │ Game events
                                    ▼
                          ┌──────────────────────┐
                          │ Azure SignalR        │
                          │ Real-time updates    │
                          │ to connected players │
                          └──────────────────────┘
```

*Target architecture. The browser handles low-latency editing, recording and playback; Azure manages shared state, media persistence and real-time coordination.*

### Technology stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | React, TypeScript, Vite | Browser-based game interface |
| Audio | Web Audio API, browser media APIs | Composition, recording and playback |
| Backend | Python 3.14, Azure Functions | HTTP APIs, game rules and round orchestration |
| Database | Azure Cosmos DB for NoSQL | Durable sessions, chains and versioned contributions |
| Real-time messaging | Azure SignalR Service | Multiplayer notifications and state synchronisation |
| Object storage | Azure Blob Storage | Audio recordings and media assets |
| Identity and security | Microsoft Entra managed identities | Service-to-service authentication |
| Engineering | GitHub Actions, pytest | Continuous integration and automated validation |

## Engineering principles

The architecture is guided by the requirements of a real multiplayer system:

- **Server-authoritative state:** game rules, round transitions and access to hidden information are controlled by the backend.
- **Concurrency-aware persistence:** conditional updates and idempotent submissions help prevent duplicate contributions and lost writes.
- **Event-driven communication:** clients receive meaningful game events instead of relying solely on repeated polling.
- **Stateless compute:** shared state belongs in cloud storage rather than a particular application instance, supporting elastic scaling.
- **Least-privilege access:** managed identities and scoped data permissions reduce reliance on long-lived credentials.
- **Testable boundaries:** clear API contracts and isolated domain logic support automated testing and maintainability.

## Project status

🚧 **ChaosComposer is in active development.** This repository represents an evolving academic software engineering project. The experience and architecture above describe the intended full product and should not be interpreted as a feature-complete release.

---

<div align="center">

**Built by Group T · University of Southampton**

*Making music is collaborative. Making chaos is multiplayer.*

</div>
