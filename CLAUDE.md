# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## ⚠️ **IMPORTANT: Project Direction Change**

**This project is transitioning from Meetily (Tauri desktop app) to Meeting Co-Pilot (web-based collaborative meeting assistant).**

**Current Status**: In Phase 0 (Discovery) - evaluating Meetily codebase for web migration.

## Project Overview

**Meeting Co-Pilot** is a web-based collaborative meeting assistant forked from Meetily. It enhances meetings through:
- **Real-time multi-participant collaboration** (web-based, no installation)
- **Live transcript** visible to all participants
- **AI-powered features** (catch-up, Q&A, decision tracking)
- **Cross-meeting context** (link related meetings, surface past decisions)

### Key Difference from Meetily
| Aspect | Meetily (Original) | Meeting Co-Pilot (Fork) |
|--------|-------------------|------------------------|
| Architecture | Tauri desktop app | Web-based (Next.js + FastAPI) |
| Users | Single user | Multi-participant sessions |
| Audio | Desktop APIs | Browser getUserMedia() |
| Use Case | Privacy-first local | Collaborative on-site meetings |

## Product Requirements Document (PRD)

**Full PRD Location**: `/docs/PRD.md` (if you've added it) or shared externally

**Key Goals**:
1. **G1**: Enable shared meeting context (all see same transcript)
2. **G2**: Eliminate "corporate amnesia" (searchable history)
3. **G3**: Support on-site meetings (room mic + laptops)
4. **G4**: Instant catch-up (AI summaries for zoned-out participants)
5. **G5**: Cross-meeting continuity (link related meetings)
6. **G6**: Automate action tracking
7. **G7**: Real-time Q&A during meetings

**Explicitly NOT Building**:
- Video/audio conferencing (not Zoom/Teams)
- System audio capture (online meetings)
- Mobile apps
- Complex auth/permissions
- Enterprise multi-tenant

## Architecture: Web vs Desktop

**Decision**: Web-based (removing Tauri)

**Rationale**:
- ✅ 95% of meetings are on-site (room mic sufficient)
- ✅ Multi-participant = URL sharing (no install)
- ✅ Faster development (no Rust/Tauri complexity)
- ✅ Lower barrier to entry (<30s join time)
- ❌ Cannot capture system audio (Zoom/Teams) - acceptable trade-off

## Current Technology Stack

### Backend (✅ Keep - Working)
- **Framework**: FastAPI (Python)
- **Database**: SQLite (aiosqlite)
- **Vector DB**: ChromaDB/LanceDB (already integrated)
- **Transcription**: Whisper.cpp (local, GPU-accelerated)
- **LLM**: Ollama (local) + Claude API (cloud fallback)

### Frontend (🔧 Needs Migration)
- **Current**: Tauri 2.x (Rust) + Next.js 14 + React 18
- **Target**: Pure Next.js 14 + React 18 (web-based)
- **To Remove**: All Tauri/Rust code
- **To Add**: Browser audio APIs, WebSocket real-time sync

## Essential Development Commands

### Backend Development (✅ Currently Working)

**Location**: `/backend`

```bash
# Docker (Recommended - Currently Running)
docker ps                           # Check running containers
./run-docker.sh logs --service app  # View backend logs

# Manual (if not using Docker)
./build_whisper.sh small            # Build Whisper with model
./clean_start_backend.sh            # Start FastAPI server (port 5167)
```

**Service Endpoints**:
- **Backend API**: http://localhost:5167
- **API Docs**: http://localhost:5167/docs
- **Whisper Server**: http://localhost:8178

### Frontend Development (🔧 In Transition)

**Location**: `/frontend`

**Current (Tauri - Being Removed)**:
```bash
pnpm run tauri:dev  # ❌ Don't use - requires Rust/Cargo
```

**Temporary (Web Dev Server)**:
```bash
cd frontend
pnpm install
pnpm run dev        # ✅ Use this - runs Next.js at http://localhost:3118
```

**Known Issues**:
- You'll see Tauri errors in browser console (expected - being removed)
- Audio recording won't work (needs browser API implementation)
- UI will load but some features are non-functional

## Implementation Plan (3-4 Weeks)

### Phase 0: Discovery & Setup ⏳ (Current Phase)
**Duration**: 2-3 days

**Tasks**:
- [ ] Explore Meetily codebase
- [ ] Identify Tauri-specific code to remove
- [ ] Test backend independently (✅ Done - running)
- [ ] Validate Whisper + Ollama work
- [ ] Create detailed migration plan
- [ ] Update this CLAUDE.md with findings

**Key Files to Review**:
- `frontend/src-tauri/` - All Rust code (will be removed)
- `frontend/src/app/page.tsx` - Main UI (needs Tauri→Web migration)
- `frontend/src/hooks/` - React hooks (some use Tauri APIs)
- `backend/app/main.py` - Backend API (keep mostly as-is)

### Phase 1: Core Web App (4-5 days)
- Remove Tauri shell from frontend
- Implement browser audio capture (getUserMedia)
- Stream audio to backend via WebSocket
- Display live transcript

### Phase 2: Multi-Participant Sessions (3-4 days)
- Session management (create, join, leave)
- WebSocket rooms for real-time sync
- Participant list and presence

### Phase 3: AI Features (4-5 days)
- Real-time decision/action extraction
- "Catch me up" feature
- Real-time Q&A with AI
- Current topic identification

### Phase 4: Cross-Meeting Context (3-4 days)
- VectorDB for meeting embeddings
- Meeting linking
- Continuity recaps

### Phase 5: Post-Meeting & Polish (3-4 days)
- Summary generation
- Export (Markdown/PDF)
- Meeting history & search

## Architecture Diagrams

### Current (Meetily - Desktop)
```
┌─────────────────────────────────────────┐
│   Frontend (Tauri Desktop App)          │
│  ┌──────────┐  ┌────────────────────┐  │
│  │ Next.js  │←→│  Rust (Audio/IPC)  │  │
│  └──────────┘  └────────────────────┘  │
│       ↑ Tauri Events                    │
└───────┼─────────────────────────────────┘
        │ HTTP
        ↓
┌───────────────────────────────────────┐
│   Backend (FastAPI)                   │
│  ┌─────────┐  ┌──────────┐           │
│  │ SQLite  │  │ Whisper  │           │
│  └─────────┘  └──────────┘           │
└───────────────────────────────────────┘
```

### Target (Meeting Co-Pilot - Web)
```
┌─────────────────────────────────────────┐
│   Frontend (Pure Web - Next.js)         │
│  ┌──────────┐  ┌────────────────────┐  │
│  │   UI     │  │  Browser Audio API │  │
│  └──────────┘  └────────────────────┘  │
│       ↑ WebSocket (Real-time Sync)      │
└───────┼─────────────────────────────────┘
        ↓
┌───────────────────────────────────────┐
│   Backend (FastAPI)                   │
│  ┌─────────┐  ┌──────────┐  ┌──────┐│
│  │ SQLite  │  │ Whisper  │  │Vector││
│  │         │  │          │  │  DB  ││
│  └─────────┘  └──────────┘  └──────┘│
└───────────────────────────────────────┘
```

## Migration Strategy: What to Keep vs Remove

### ✅ KEEP (60-70% of Meetily)
- **Backend**: Entire FastAPI app
  - Meeting CRUD operations
  - Whisper integration
  - LLM summarization
  - VectorDB for embeddings
- **Frontend UI**: Most React components
  - Meeting list
  - Transcript display
  - Summary view
  - Settings

### 🔧 MODIFY (Significant Changes)
- **Audio Capture**: Tauri APIs → Browser getUserMedia()
- **Real-time Communication**: Single-user → Multi-user WebSocket
- **State Management**: Add session/participant tracking
- **Q&A**: Single-user → Private per-participant

### ❌ REMOVE (Desktop-Specific)
- **All Rust Code**: `frontend/src-tauri/` directory
- **Tauri Dependencies**: package.json, Cargo.toml
- **Desktop Build Scripts**: clean_run.sh, etc.
- **Platform-Specific**: Audio device platform code (Windows/macOS/Linux)

## Key Files Reference

### Backend (✅ Keep - No Changes Needed)
- `backend/app/main.py` - FastAPI app, API endpoints
- `backend/app/db.py` - Database operations
- `backend/app/summarization.py` - LLM summarization
- `backend/app/vectordb.py` - Embedding storage

### Frontend (🔧 Needs Migration)
**To Remove**:
- `frontend/src-tauri/` - Entire Rust codebase
- `frontend/src/hooks/usePermissionCheck.ts` - Uses Tauri APIs
- All `invoke()` and `listen()` calls from `@tauri-apps/api`

**To Modify**:
- `frontend/src/app/page.tsx` - Main recording interface
- `frontend/src/components/Sidebar/SidebarProvider.tsx` - Add session state
- `frontend/src/hooks/` - Replace Tauri hooks with web APIs

**To Add (New)**:
- `frontend/src/lib/websocket.ts` - WebSocket client
- `frontend/src/lib/audio.ts` - Browser audio capture
- `frontend/src/contexts/SessionContext.tsx` - Multi-user session state

## Common Development Tasks (During Migration)

### Identifying Tauri Code to Remove
```bash
# Search for Tauri imports
cd frontend
grep -r "@tauri-apps/api" src/

# Search for invoke calls
grep -r "invoke(" src/

# Search for listen calls
grep -r "listen(" src/
```

### Testing Backend Independently
```bash
# Backend should already be running (Docker)
curl http://localhost:5167/get-meetings
curl http://localhost:5167/docs  # Swagger UI
```

### Browser Audio Capture (To Implement)
```typescript
// Replace Tauri audio with:
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const mediaRecorder = new MediaRecorder(stream);
// Stream to backend via WebSocket
```

## Important Constraints & Decisions

1. **On-Site Meetings Only**: 95% use case, room microphone sufficient
2. **No System Audio**: Cannot capture Zoom/Teams (desktop app required)
3. **Web Browser Only**: Desktop/laptop browsers, no mobile
4. **Single-Instance Deployment**: No multi-tenant for MVP
5. **Session-Based Access**: No complex auth for MVP

## Repository Conventions

- **Logging Format**: Backend uses detailed formatting with filename:line:function
- **Error Handling**: Backend uses Python exceptions, frontend uses try-catch
- **Git Branches**:
  - `main`: Stable releases
  - `feature/web-migration`: Current work (if created)
  - `feature/*`: New features
  - `fix/*`: Bug fixes

## Testing & Debugging

### Backend (Already Running)
```bash
# View logs
docker logs meetily-backend -f

# Test endpoints
curl http://localhost:5167/get-meetings
```

### Frontend (During Migration)
```bash
cd frontend
pnpm run dev
# Open http://localhost:3118
# Check browser console for errors
```

**Expected Errors (Temporary)**:
- `window.__TAURI_INTERNALS__ is undefined` - Normal, removing Tauri
- CORS errors for Ollama - Normal, will fix with proper WebSocket

## Phase 0 Discovery Checklist ✅ COMPLETED

**Audio System**:
- [x] Understand how Tauri captures microphone
- [x] Identify VAD (Voice Activity Detection) logic
- [x] Check if Whisper integration is Tauri-dependent

**Real-Time Features**:
- [x] How does live transcript update work?
- [x] Is there any WebSocket code already?
- [x] How are decisions/actions extracted?

**Database & Backend**:
- [x] Backend is independent (confirmed running)
- [x] Check VectorDB integration
- [x] Understand meeting storage schema

**Frontend State**:
- [x] How is recording state managed?
- [x] What React contexts exist?
- [x] Which components are Tauri-dependent?

### Phase 0 Findings Summary

**Backend Architecture** ✅:
- **FastAPI**: Fully functional on port 5167, comprehensive HTTP endpoints
- **Database**: SQLite with complete schema (meetings, transcripts, summary_processes, settings)
- **LLM Integration**: Working with pydantic-ai (Claude, OpenAI, Groq, Ollama)
- **Whisper Server**: Running on port 8178, accepts HTTP POST with WAV files
- **Audio Flow**: Whisper receives WAV files via HTTP POST → returns transcript text
- **VectorDB**: ❌ NOT IMPLEMENTED (ChromaDB mentioned in PRD but no code found)

**Backend Gaps** ⚠️:
1. **No WebSocket Support**: All endpoints are HTTP-only (needs implementation)
2. **No Real-Time Streaming**: Current flow is batch-based (full WAV files, not chunks)
3. **No Multi-User Sessions**: Database has no `sessions` or `participants` tables
4. **No VectorDB**: No ChromaDB/LanceDB integration found (Phase 4 requirement)

**Frontend Tauri Dependencies** ❌:
- **Total Rust Files**: 100+ files in `frontend/src-tauri/` (ALL to be removed)
- **Audio Capture**: Platform-specific code (Windows/macOS/Linux device detection)
- **VAD**: Voice Activity Detection in Rust (can replace with browser AudioContext)
- **Transcription Flow**: Rust → HTTP POST WAV → Whisper → Tauri events → React
- **Critical Files**:
  - `src-tauri/src/audio/transcription/whisper_provider.rs` - HTTP POST to Whisper
  - `src/contexts/RecordingStateContext.tsx` - Uses `invoke()` and `listen()`
  - `src/components/RecordingControls.tsx` - Tauri commands

**Audio Format Challenge** 🚨:
- **Current**: Rust captures audio → encodes to WAV/PCM → sends to Whisper
- **Target**: Browser MediaRecorder → outputs WebM/Opus → needs conversion to WAV
- **Solution**: Use ffmpeg in backend to convert WebM → WAV before Whisper

## Next Steps (Ready for Phase 1)

Phase 0 is **COMPLETE**. Full findings and implementation plan available in:
- **Detailed Plan**: `/docs/PHASE_1_PLAN.md`
- **Timeline**: 5-7 working days
- **Start Date**: Jan 2, 2025 (when user returns from leave)

**Phase 1 Quick Summary**:
- Day 1-2: Remove Tauri dependencies
- Day 3-4: Implement browser audio capture (getUserMedia + MediaRecorder)
- Day 5-6: Add backend WebSocket endpoint + ffmpeg conversion
- Day 7: Testing and polish

**Key Risks**:
1. Audio format conversion (WebM → WAV) - mitigated with ffmpeg
2. Real-time latency - need to test 1-2s chunk sizes
3. WebSocket stability - implement reconnection logic

---

**This file auto-updates as we progress through phases. Last updated: Phase 0 (Discovery Complete) - Dec 24, 2025**
