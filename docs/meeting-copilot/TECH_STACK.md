# Meeting Co-Pilot — Technology Stack Guide

**Version**: 1.0
**Last Updated**: Dec 24, 2025
**Audience**: Technical stakeholders, developers, senior management

---

## Table of Contents

1. [Overview](#overview)
2. [Frontend Stack](#frontend-stack)
3. [Backend Stack](#backend-stack)
4. [AI & Machine Learning](#ai--machine-learning)
5. [Data Storage](#data-storage)
6. [Real-Time Communication](#real-time-communication)
7. [Audio Processing](#audio-processing)
8. [Development & Deployment](#development--deployment)
9. [Complete Technology Diagram](#complete-technology-diagram)

---

## Overview

Meeting Co-Pilot uses a modern, proven technology stack optimized for:
- **Real-time collaboration** (WebSocket-based)
- **AI-powered features** (Whisper, LLMs)
- **Fast development** (TypeScript, Python)
- **Privacy-first** (local processing options)

**Architecture Pattern**: Client-Server with Real-Time Sync

```
Browser (Next.js) ←→ WebSocket ←→ FastAPI Server ←→ Whisper.cpp / LLMs
                                          ↓
                                   SQLite + VectorDB
```

---

## Frontend Stack

### 1. **Next.js 14** (React Framework)

**What it is**: Full-stack React framework with server-side rendering and API routes

**What it does**:
- Renders the web UI (meeting interface, transcript view, controls)
- Handles client-side routing (`/meeting/[id]`, `/history`)
- Manages browser audio capture (getUserMedia API)
- Sends/receives real-time data via WebSocket

**Why we use it**:
- ✅ **Production-proven**: Used by Vercel, Netflix, Twitch
- ✅ **Fast page loads**: Server-side rendering improves initial load time
- ✅ **Built-in routing**: File-based routing reduces boilerplate
- ✅ **TypeScript support**: Type safety across frontend/backend
- ✅ **Already in Meetily**: 60% of UI components can be reused

**Alternatives considered**: Vite + React (more manual setup), SvelteKit (smaller ecosystem)

---

### 2. **React 18** (UI Library)

**What it is**: JavaScript library for building user interfaces with components

**What it does**:
- Creates reusable UI components (TranscriptView, ParticipantList, ActionPanel)
- Manages UI state (recording status, participant list, transcript updates)
- Handles user interactions (click "Catch Me Up", ask AI questions)

**Why we use it**:
- ✅ **Component-based**: Easy to build complex UIs from small pieces
- ✅ **Large ecosystem**: Thousands of ready-to-use component libraries
- ✅ **Concurrent rendering**: React 18 handles real-time updates efficiently
- ✅ **Familiar**: Most developers know React

**Key React features we use**:
- **Hooks**: `useState`, `useEffect`, `useContext` for state management
- **Context API**: Share meeting state across components without prop drilling
- **Suspense**: Handle async data loading gracefully

---

### 3. **TypeScript** (Programming Language)

**What it is**: JavaScript with static type checking

**What it does**:
- Catches bugs at compile-time (e.g., passing wrong type to function)
- Provides autocomplete and IntelliSense in VS Code
- Documents code with type annotations

**Why we use it**:
- ✅ **Fewer runtime errors**: Type errors caught before deployment
- ✅ **Better DX**: Autocomplete makes development faster
- ✅ **Self-documenting**: Types serve as inline documentation
- ✅ **Refactoring safety**: Renaming variables updates all references

**Example**:
```typescript
interface Transcript {
  id: string;
  text: string;
  speaker: string;
  timestamp: Date;
}

function addTranscript(transcript: Transcript) {
  // TypeScript ensures transcript has correct shape
}
```

---

### 4. **Tailwind CSS** (Styling Framework)

**What it is**: Utility-first CSS framework

**What it does**:
- Styles UI components with utility classes
- Ensures consistent spacing, colors, typography
- Provides responsive design utilities

**Why we use it**:
- ✅ **Fast styling**: Write CSS directly in JSX
- ✅ **Consistent design**: Predefined design tokens (colors, spacing)
- ✅ **Small bundle**: Tree-shakes unused styles
- ✅ **Already in Meetily**: Keeps UI consistent

**Example**:
```tsx
<button className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
  Start Recording
</button>
```

---

### 5. **pnpm** (Package Manager)

**What it is**: Fast, disk-efficient package manager (alternative to npm/yarn)

**What it does**:
- Installs JavaScript dependencies (React, Next.js, etc.)
- Manages project dependencies and versions
- Creates symlinks to save disk space

**Why we use it**:
- ✅ **Faster installs**: 2-3x faster than npm
- ✅ **Disk efficient**: Shared dependencies across projects
- ✅ **Already in Meetily**: Keeps tooling consistent

---

## Backend Stack

### 6. **FastAPI** (Python Web Framework)

**What it is**: Modern, fast Python web framework for building APIs

**What it does**:
- Handles HTTP requests (create meeting, get transcript, etc.)
- Manages WebSocket connections for real-time sync
- Orchestrates audio processing and AI services
- Serves meeting data from database

**Why we use it**:
- ✅ **Fast development**: Auto-generates API docs (Swagger UI)
- ✅ **Async support**: Non-blocking I/O for WebSocket and AI calls
- ✅ **Type hints**: Python 3.11+ type hints prevent bugs
- ✅ **AI/ML ecosystem**: Easy integration with Whisper, LLMs
- ✅ **Already in Meetily**: Backend is fully functional

**Example**:
```python
@app.websocket("/ws/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        audio_chunk = await websocket.receive_bytes()
        transcript = await process_audio(audio_chunk)
        await websocket.send_json({"text": transcript})
```

**API Documentation**: Auto-generated at `http://localhost:5167/docs`

---

### 7. **Python 3.11+** (Programming Language)

**What it is**: High-level programming language

**What it does**:
- Runs backend server (FastAPI)
- Processes audio (conversion, streaming)
- Interfaces with AI models (Whisper, LLMs)
- Database operations (SQLite queries)

**Why we use it**:
- ✅ **Rich AI ecosystem**: Whisper, Ollama, pydantic-ai all use Python
- ✅ **Fast development**: Clean syntax, huge standard library
- ✅ **Async/await**: Built-in async support for WebSockets
- ✅ **Type hints**: Modern Python has type safety

**Version requirement**: Python 3.11+ for performance improvements

---

### 8. **Uvicorn** (ASGI Server)

**What it is**: Lightning-fast ASGI server for Python

**What it does**:
- Runs the FastAPI application
- Handles HTTP and WebSocket connections
- Manages concurrent requests

**Why we use it**:
- ✅ **Fast**: Built on uvloop (faster event loop)
- ✅ **WebSocket support**: Native WebSocket handling
- ✅ **Production-ready**: Used by major companies

**Command**: `uvicorn app.main:app --host 0.0.0.0 --port 5167`

---

## AI & Machine Learning

### 9. **Whisper.cpp** (Speech-to-Text Engine)

**What it is**: C++ implementation of OpenAI's Whisper model (optimized for CPU/GPU)

**What it does**:
- Converts audio (WAV files) to text transcripts
- Performs speaker diarization (identifies Speaker 1, 2, 3...)
- Runs locally on server (no cloud API calls)

**Why we use it**:
- ✅ **Fast**: GPU-accelerated (CUDA/Metal support)
- ✅ **Accurate**: OpenAI Whisper is state-of-the-art
- ✅ **Privacy**: Runs locally, no audio sent to cloud
- ✅ **Free**: No API costs
- ✅ **Already in Meetily**: Fully integrated and working

**Model options**:
- `tiny` (75 MB) — Fast, lower accuracy
- `small` (466 MB) — ⭐ **Recommended** for development
- `medium` (1.5 GB) — Higher accuracy
- `large-v3` (3 GB) — Best accuracy, slower

**Latency**: < 2 seconds for 30-second audio chunk

**API Endpoint**: `http://localhost:8178` (HTTP POST with WAV file)

---

### 10. **Claude API** (Cloud LLM - Primary/Default)

**What it is**: Anthropic's high-quality language model API

**What it does**:
- Provides high-quality AI responses (default system)
- Handles all AI features (summarization, Q&A, extraction)
- Streams audio/transcript data to cloud instantly
- Prevents data loss on browser crash

**Why we use it as PRIMARY**:
- ✅ **Enterprise-grade**: Data NOT used for training (contractual guarantee)
- ✅ **High quality**: Best-in-class reasoning and summarization
- ✅ **Reliable**: Cloud-based, always available, no setup needed
- ✅ **Fast**: Lower latency than local LLMs
- ✅ **Real-time Cloud Sync**: Audio/transcript streams to cloud → no data loss on crash

**When used**:
- **Default mode** for all users
- All AI features (Catch Me Up, Q&A, extraction, summaries)
- Real-time sync to prevent data loss

**Cost**: Pay-per-token (acceptable for office deployment)

**NFR Requirement**: Per NFR2, Claude/OpenAI ensures enterprise-grade quality and real-time cloud sync

---

### 11. **Ollama** (Local LLM Runtime - Optional Privacy Mode)

**What it is**: Run large language models locally (like Docker for LLMs)

**What it does**:
- Runs LLMs locally (Llama 3.1, Mistral, etc.) when user enables "Privacy Toggle"
- Provides OpenAI-compatible API
- Handles model loading and inference
- Keeps all data on-premises

**Why we offer it as OPTIONAL**:
- ✅ **Privacy**: All AI processing stays local (for privacy-conscious users)
- ✅ **Cost**: No API fees (for cost-sensitive deployments)
- ✅ **Offline**: Works without internet
- ✅ **GPU-accelerated**: Fast inference with CUDA/Metal

**When used**:
- User explicitly enables "Privacy Toggle" in settings
- Compliance requirements mandate on-premises processing
- Cost optimization for high-volume usage

**Trade-offs**:
- ⚠️ **Lower quality**: Local models are less capable than Claude
- ⚠️ **Slower**: Inference takes longer (especially without GPU)
- ⚠️ **No cloud sync**: Data loss possible on browser crash
- ⚠️ **Setup required**: Need to download models, configure GPU

**Example models**:
- `llama3.1:8b` — Fast, good for real-time features
- `mistral:7b` — Efficient, good balance
- `gemma:7b` — Lightweight

**System Default**: Claude API (can switch to Ollama via Privacy Toggle)

---

### 12. **pydantic-ai** (AI Orchestration Framework)

**What it is**: Python framework for structured AI interactions

**What it does**:
- Manages LLM calls (Ollama, Claude, OpenAI)
- Enforces structured outputs (JSON schemas)
- Handles prompt templates
- Switches between providers seamlessly

**Why we use it**:
- ✅ **Type-safe**: Pydantic models ensure correct AI output
- ✅ **Multi-provider**: Easy to switch Ollama ↔ Claude
- ✅ **Already in Meetily**: Fully integrated

**Example**:
```python
from pydantic_ai import Agent

class ActionItem(BaseModel):
    task: str
    owner: str
    deadline: str

agent = Agent(model="ollama:llama3.1")
result = await agent.run(
    "Extract action items from transcript",
    response_type=list[ActionItem]
)
```

---

## Data Storage

### 13. **SQLite** (Relational Database)

**What it is**: Serverless SQL database (single file)

**What it does**:
- Stores meetings metadata (title, date, duration)
- Stores transcripts (speaker, text, timestamp)
- Stores action items and decisions
- Stores participant information

**Why we use it**:
- ✅ **Simple**: No database server required
- ✅ **Fast**: Direct file access, no network latency
- ✅ **Reliable**: ACID-compliant transactions
- ✅ **Portable**: Single file, easy backup
- ✅ **Good for MVP**: Easy to migrate to PostgreSQL later

**Database schema** (simplified):
```sql
meetings (id, title, start_time, end_time, status)
transcripts (id, meeting_id, speaker, text, timestamp)
action_items (id, meeting_id, task, owner, deadline, status)
decisions (id, meeting_id, decision_text, timestamp)
participants (id, meeting_id, name, joined_at, role)
```

**Migration path**: Can switch to PostgreSQL for multi-tenant deployment

---

### 14. **aiosqlite** (Async SQLite Library)

**What it is**: Async wrapper for SQLite

**What it does**:
- Enables non-blocking database queries
- Works with FastAPI's async/await
- Prevents database from blocking WebSocket connections

**Why we use it**:
- ✅ **Non-blocking**: Database queries don't block real-time features
- ✅ **FastAPI compatible**: Works with async endpoints
- ✅ **Already in Meetily**: No changes needed

---

### 15. **ChromaDB** (Vector Database)

**What it is**: Embedding database for semantic search

**What it does**:
- Stores meeting embeddings (vector representations)
- Enables semantic search ("What did we decide about pricing?")
- Powers cross-meeting context (searches past meetings)
- Enables Q&A with source citations

**Why we use it**:
- ✅ **Embedded**: No external server (like SQLite for vectors)
- ✅ **Fast**: Optimized for similarity search
- ✅ **Python-native**: Easy FastAPI integration
- ✅ **Free**: Open-source

**How it works**:
1. Meeting transcript → Split into chunks
2. Each chunk → Convert to embedding (vector)
3. Store in ChromaDB with metadata (meeting_id, timestamp)
4. User asks question → Convert to embedding → Find similar chunks
5. Return relevant transcript sections with source citations

**Alternative**: LanceDB (similar, more features)

**Phase**: Implemented in Phase 4

---

## Real-Time Communication

### 16. **WebSocket** (Real-Time Protocol)

**What it is**: Bidirectional communication protocol (upgrade from HTTP)

**What it does**:
- Streams audio from browser to backend
- Broadcasts transcript updates to all participants
- Sends real-time AI responses (Q&A, summaries)
- Notifies participants of join/leave events

**Why we use it**:
- ✅ **Bidirectional**: Server can push updates to clients
- ✅ **Low latency**: No polling overhead
- ✅ **Native browser support**: All modern browsers support WebSocket
- ✅ **FastAPI support**: Built-in WebSocket endpoints

**Example flow**:
```
Browser → WebSocket → Backend → Process → Broadcast to all participants
```

**Connection management**: Auto-reconnect on disconnect

---

### 17. **Socket.IO** (WebSocket Library - Optional)

**What it is**: Enhanced WebSocket library with fallbacks

**What it does**:
- Manages WebSocket connections with reconnection logic
- Provides room-based broadcasting (per-meeting isolation)
- Falls back to polling if WebSocket unavailable

**Why we might use it**:
- ✅ **Automatic reconnection**: Handles network issues gracefully
- ✅ **Room support**: Easy to broadcast to specific meetings
- ✅ **Fallback**: Works even if WebSocket is blocked

**Phase**: May add in Phase 2 if native WebSocket has issues

---

## Audio Processing

### 18. **MediaRecorder API** (Browser API)

**What it is**: Built-in browser API for recording audio

**What it does**:
- Captures microphone input in browser
- Encodes audio to WebM/Opus format
- Provides audio chunks in real-time

**Why we use it**:
- ✅ **Native browser API**: No library needed
- ✅ **Modern**: Supported in all major browsers
- ✅ **Efficient**: Hardware-accelerated encoding

**Replaces**: Tauri's Rust audio capture

**Browser support**: Chrome, Firefox, Safari, Edge (latest versions)

---

### 19. **getUserMedia API** (Browser API)

**What it is**: Browser API for accessing microphone/camera

**What it does**:
- Requests microphone permission from user
- Provides audio stream (MediaStream)
- Lists available audio input devices

**Why we use it**:
- ✅ **Standard**: Part of WebRTC spec
- ✅ **Secure**: Requires HTTPS and user permission
- ✅ **Device selection**: User can choose specific microphone

**Example**:
```typescript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    sampleRate: 16000
  }
});
```

---

### 20. **ffmpeg** (Audio Conversion Tool)

**What it is**: Swiss Army knife for audio/video processing

**What it does**:
- Converts WebM (from browser) → WAV (for Whisper)
- Resamples audio to 16kHz mono (Whisper requirement)
- Processes audio chunks in real-time

**Why we use it**:
- ✅ **Format conversion**: Browser outputs WebM, Whisper needs WAV
- ✅ **Fast**: Hardware-accelerated
- ✅ **Reliable**: Industry-standard tool
- ✅ **Free**: Open-source

**Command example**:
```bash
ffmpeg -i input.webm -ar 16000 -ac 1 -f wav output.wav
```

**Phase**: Critical for Phase 1 (browser audio → Whisper)

---

## Development & Deployment

### 21. **Docker** (Containerization)

**What it is**: Platform for running applications in containers

**What it does**:
- Packages backend + Whisper + dependencies
- Ensures consistent environment (dev = prod)
- Simplifies deployment

**Why we use it**:
- ✅ **Consistent**: Same environment on all machines
- ✅ **Isolated**: No dependency conflicts
- ✅ **Easy deployment**: Single `docker-compose up`
- ✅ **Already in Meetily**: Docker setup works perfectly

**Containers**:
- `backend`: FastAPI server (port 5167)
- `whisper`: Whisper.cpp server (port 8178)

**Command**: `./run-docker.sh`

---

### 22. **Docker Compose** (Multi-Container Orchestration)

**What it is**: Tool for defining multi-container Docker applications

**What it does**:
- Starts backend + Whisper together
- Manages networking between containers
- Handles environment variables

**Why we use it**:
- ✅ **Simple**: One command to start all services
- ✅ **Declarative**: Config in `docker-compose.yml`

---

### 23. **Git** (Version Control)

**What it is**: Distributed version control system

**What it does**:
- Tracks code changes
- Enables collaboration
- Provides rollback capability

**Why we use it**:
- ✅ **Industry standard**: Everyone knows Git
- ✅ **GitHub integration**: Easy to share/review code
- ✅ **Branch strategy**: Feature branches for each phase

---

### 24. **VS Code** (Code Editor)

**What it is**: Popular code editor from Microsoft

**Why we use it**:
- ✅ **TypeScript support**: Best-in-class TypeScript tooling
- ✅ **Extensions**: Python, React, Docker extensions
- ✅ **Integrated terminal**: Run commands without leaving editor
- ✅ **Git integration**: Built-in Git GUI

---

## Complete Technology Diagram

### Full Stack Visualization

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Browser)                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Next.js 14 + React 18 + TypeScript                      │  │
│  │  - Tailwind CSS (styling)                                │  │
│  │  - getUserMedia API (mic access)                         │  │
│  │  - MediaRecorder API (audio capture)                     │  │
│  │  - WebSocket client (real-time)                          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓ WebSocket / HTTP
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND (FastAPI Server)                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  FastAPI + Python 3.11 + Uvicorn                         │  │
│  │  - WebSocket handler (real-time sync)                    │  │
│  │  - Session management                                    │  │
│  │  - Audio processing (ffmpeg conversion)                  │  │
│  │  - AI orchestration (pydantic-ai)                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ↓                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐    │
│  │   SQLite     │  │  ChromaDB    │  │  Whisper.cpp      │    │
│  │  (meetings,  │  │  (embeddings,│  │  (transcription)  │    │
│  │  transcripts)│  │   vectors)   │  │  Port 8178        │    │
│  └──────────────┘  └──────────────┘  └───────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ↓ API calls
┌─────────────────────────────────────────────────────────────────┐
│                         AI PROVIDERS                             │
│  ┌──────────────┐                    ┌──────────────┐          │
│  │  Claude API  │                    │   Ollama     │          │
│  │ (PRIMARY/    │                    │  (Optional   │          │
│  │  Default)    │                    │  Privacy     │          │
│  │              │                    │  Toggle)     │          │
│  └──────────────┘                    └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘

DEPLOYMENT LAYER:
┌─────────────────────────────────────────────────────────────────┐
│  Docker + Docker Compose                                         │
│  - backend container (FastAPI)                                   │
│  - whisper container (Whisper.cpp)                               │
│  - Volume mounts (SQLite, models)                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Decision Summary

| Category | Technology | Why Chosen | Phase Used |
|----------|-----------|------------|------------|
| **Frontend Framework** | Next.js 14 | Server-side rendering, built-in routing, already in Meetily | All |
| **UI Library** | React 18 | Component-based, large ecosystem, concurrent rendering | All |
| **Language (Frontend)** | TypeScript | Type safety, better DX, self-documenting | All |
| **Styling** | Tailwind CSS | Fast styling, consistent design, already in Meetily | All |
| **Package Manager** | pnpm | Faster installs, disk efficient | All |
| **Backend Framework** | FastAPI | Fast development, async, AI-friendly, already in Meetily | All |
| **Language (Backend)** | Python 3.11+ | Rich AI ecosystem, async support | All |
| **Server** | Uvicorn | Fast ASGI server, WebSocket support | All |
| **Transcription** | Whisper.cpp | Local, fast, accurate, free, already in Meetily | 1, 2, 3 |
| **LLM (Primary)** | Claude API | Enterprise-grade, high quality, cloud sync, default system | 3, 4 |
| **LLM (Optional)** | Ollama | Privacy toggle for local-only processing | 3, 4 |
| **AI Framework** | pydantic-ai | Type-safe, multi-provider, already in Meetily | 3, 4 |
| **Database** | SQLite | Simple, fast, portable, already in Meetily | All |
| **Async DB** | aiosqlite | Non-blocking, FastAPI compatible | All |
| **Vector DB** | ChromaDB | Embedded, fast, Python-native | 4 |
| **Real-Time** | WebSocket | Bidirectional, low latency, native browser support | 1, 2, 3 |
| **Audio API** | getUserMedia + MediaRecorder | Native browser APIs, no library needed | 1 |
| **Audio Conversion** | ffmpeg | WebM → WAV conversion for Whisper | 1 |
| **Containerization** | Docker + Compose | Consistent environment, easy deployment | All |
| **Version Control** | Git + GitHub | Industry standard, collaboration | All |

---

## Key Technology Trade-offs

### 1. **SQLite vs PostgreSQL**
- **Chose**: SQLite
- **Why**: Simpler for MVP, single-user instance, easy migration path
- **Trade-off**: Won't scale to multi-tenant (acceptable for office deployment)

### 2. **Claude API vs Ollama-only**
- **Chose**: Claude API (primary) + Ollama (optional privacy toggle)
- **Why**: Enterprise-grade quality, cloud sync prevents data loss, reliable
- **Trade-off**: API costs (acceptable for office deployment), requires internet

### 3. **Native WebSocket vs Socket.IO**
- **Chose**: Native WebSocket first
- **Why**: Simpler, no extra dependencies
- **Trade-off**: Manual reconnection logic (can add Socket.IO if needed)

### 4. **Whisper.cpp vs Cloud Transcription**
- **Chose**: Whisper.cpp (local)
- **Why**: Privacy, free, fast with GPU
- **Trade-off**: Requires GPU for best performance (acceptable - office has GPUs)

---

## Technology Maturity & Risk Assessment

| Technology | Maturity | Risk Level | Mitigation |
|------------|----------|------------|------------|
| Next.js 14 | Stable | 🟢 Low | Production-proven, large community |
| FastAPI | Stable | 🟢 Low | Widely used, excellent docs |
| Whisper.cpp | Stable | 🟢 Low | Already working in Meetily |
| Ollama | Growing | 🟡 Medium | Cloud fallback if issues |
| ChromaDB | Growing | 🟡 Medium | Can switch to LanceDB/pgvector |
| WebSocket | Stable | 🟢 Low | Native browser support |
| SQLite | Mature | 🟢 Low | Battle-tested, used everywhere |

---

## Development Tools Summary

**Frontend Development**:
```bash
cd frontend
pnpm install          # Install dependencies
pnpm run dev          # Start dev server (http://localhost:3118)
pnpm run build        # Production build
pnpm run type-check   # TypeScript validation
```

**Backend Development**:
```bash
cd backend
./run-docker.sh       # Start backend + Whisper in Docker
# OR manually:
source venv/bin/activate
python app/main.py    # Start FastAPI (http://localhost:5167)
```

**Access Points**:
- Frontend: http://localhost:3118
- Backend API: http://localhost:5167
- API Docs: http://localhost:5167/docs
- Whisper: http://localhost:8178

---

## Learning Resources

**Frontend**:
- Next.js: https://nextjs.org/docs
- React: https://react.dev
- TypeScript: https://www.typescriptlang.org/docs
- Tailwind: https://tailwindcss.com/docs

**Backend**:
- FastAPI: https://fastapi.tiangolo.com
- Python Async: https://docs.python.org/3/library/asyncio.html
- pydantic-ai: https://ai.pydantic.dev

**AI**:
- Whisper.cpp: https://github.com/ggerganov/whisper.cpp
- Ollama: https://ollama.ai/docs
- Claude API: https://docs.anthropic.com

**Databases**:
- SQLite: https://www.sqlite.org/docs.html
- ChromaDB: https://docs.trychroma.com

---

**Document Status**: Complete
**Next Update**: After Phase 1 (if tech stack changes)
**Maintained By**: Meeting Co-Pilot Team
