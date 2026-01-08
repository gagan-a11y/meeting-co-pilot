# Meeting Co-Pilot Documentation

**Meeting Co-Pilot** is a web-based collaborative meeting assistant built for real office use. This directory contains all documentation for building and deploying Meeting Co-Pilot.

> 📝 **Note**: This project is forked from Meetily (desktop app) but is being rebuilt as a web application with multi-user collaboration features for office teams.

---

## 📚 Documentation Index

### Core Documents
- **[PRD.md](PRD.md)** - Product Requirements Document
  - Complete feature specifications
  - Architecture decisions (Web vs Desktop)
  - User flows with diagrams
  - Implementation timeline with dates (estimates only)

- **[PROGRESS_REPORT.md](PROGRESS_REPORT.md)** - Progress Report ⭐ **NEW**
  - Phase-by-phase progress tracking
  - Completed tasks and deliverables
  - Key findings and insights
  - Upcoming milestones and next steps

- **[TECH_STACK.md](TECH_STACK.md)** - Technology Stack Guide
  - Detailed explanation of all tools and technologies
  - Why each technology is used
  - Complete stack visualization
  - Learning resources

### Implementation Plans
- **[PHASE_1_PLAN.md](PHASE_1_PLAN.md)** - Web Audio Foundation (5-7 days)
  - Remove desktop dependencies (Tauri/Rust)
  - Implement browser-based audio capture
  - Real-time transcription via WebSocket
  - **Target**: Single-user web recording working

- **PHASE_2_PLAN.md** *(Coming Soon)* - Multi-User Sessions (3-4 days)
  - Session management (create, join, leave)
  - WebSocket rooms for real-time sync
  - Participant list and presence
  - **Target**: Multiple participants in same meeting

- **PHASE_3_PLAN.md** *(Coming Soon)* - AI Features (4-5 days)
  - Real-time decision/action extraction
  - "Catch me up" summaries
  - Live Q&A with AI
  - **Target**: Smart meeting assistance

- **PHASE_4_PLAN.md** *(Coming Soon)* - Cross-Meeting Context (3-4 days)
  - VectorDB integration (ChromaDB)
  - Meeting linking and search
  - **Target**: Full PRD features

### Project Context
- **[/CLAUDE.md](../../CLAUDE.md)** - Main development guide
  - Phase 0 discovery findings
  - Current vs target architecture
  - Development environment setup

---

## 🗂️ Repository Structure

```
meeting-co-pilot/
├── docs/
│   ├── meeting-copilot/              # Meeting Co-Pilot docs (THIS)
│   │   ├── README.md
│   │   ├── PHASE_1_PLAN.md
│   │   └── [Future phase plans]
│   │
│   └── [meetily-original/]           # Original Meetily docs (reference)
│
├── CLAUDE.md                          # Main dev guide
├── backend/                           # FastAPI backend
├── frontend/                          # Next.js frontend
└── ...
```

---

## 🎯 Project Goals

### What We're Building
A **web-based collaborative meeting assistant** for office teams:

1. **Real-Time Collaboration**
   - Multiple participants see same live transcript
   - No installation (just URL)
   - Works with room mics or laptops

2. **AI-Powered Features**
   - Live transcription (Whisper.cpp)
   - Auto action item extraction
   - "Catch me up" for late joiners
   - Q&A with meeting context

3. **Cross-Meeting Intelligence**
   - Link related meetings
   - Surface past decisions
   - Track action items over time

---

## 📅 Development Timeline

**Current Status**: Phase 0 Complete ✅

| Phase | Duration | Dates | Status | Deliverable |
|-------|----------|-------|--------|-------------|
| **Phase 0: Discovery** | 2-3 days | Dec 22-24 | ✅ Done | Plans ready |
| **Phase 1: Web Audio** | 5-7 days | Jan 2-10 | 🔜 Next | Web recording |
| **Phase 2: Multi-User** | 3-4 days | Jan 13-17 | 📋 Plan | Shared sessions |
| **Phase 3: AI Features** | 4-5 days | Jan 20-24 | 📋 Plan | Smart assist |
| **Phase 4: Context** | 3-4 days | Jan 27-31 | 📋 Plan | Full features |

**Demo-Ready**: January 24, 2025

---

## 🚀 Quick Start

### Backend
```bash
cd backend
./run-docker.sh
# Backend: http://localhost:5167
# Whisper: http://localhost:8178
```

### Frontend
```bash
cd frontend
pnpm install
pnpm run dev
# Frontend: http://localhost:3118
```

---

## 🏗️ Technology Stack

| Component | Technology | Why? |
|-----------|-----------|------|
| Frontend | Next.js 14, React 18 | Modern web, great DX |
| Backend | FastAPI, Python | Fast async, ML ready |
| Database | SQLite | Simple, local |
| Transcription | Whisper.cpp | Fast, GPU, local |
| LLM | Ollama OR Claude | User choice |
| VectorDB | ChromaDB *(Phase 4)* | Embeddings search |
| Real-Time | WebSocket | Browser ↔ backend |

---

## 📊 Success Criteria

### Phase 1 Success
- ✅ Browser recording (Chrome, Firefox, Edge)
- ✅ Real-time transcription (< 3s)
- ✅ No desktop dependencies
- ✅ Stable 10+ min sessions

### Project Success
- ✅ 5+ team members using regularly
- ✅ AI features demonstrably useful
- ✅ < 3s average latency
- ✅ 95%+ uptime during office hours

---

## 🔗 Key Resources

### Documentation
- [CLAUDE.md](../../CLAUDE.md) - Dev guide
- [PHASE_1_PLAN.md](PHASE_1_PLAN.md) - Current phase
- [Original Meetily Docs](../) - Reference

### External
- [FastAPI](https://fastapi.tiangolo.com/)
- [Next.js](https://nextjs.org/docs)
- [Whisper.cpp](https://github.com/ggergan/whisper.cpp)

---

## 📚 Documentation Index

### Phase Documentation
- [Phase 1 Plan](./PHASE_1_PLAN.md) - Foundation & Basic Recording
- [Phase 2 Plan](./PHASE_2_PLAN.md) - AI Integration & Summaries  
- [Phase 3 Plan](./PHASE_3_PLAN.md) - Advanced AI Features (Current)
- [Phase 4 Plan](./PHASE_4_PLAN.md) - Production Hardening

### Architecture & Technical Guides
- [Chat Memory Architecture](./CHAT_MEMORY_ARCHITECTURE.md) - Complete storage and memory system (A to Z)
- [Context Flow Explained](./CONTEXT_FLOW_EXPLAINED.md) - How meeting context search works
- [Cross-Meeting Search](./CROSS_MEETING_SEARCH.md) - Vector search technical deep dive

### Feature Guides
- [Catch Me Up](./CATCH_ME_UP.md) - Real-time meeting summaries for late joiners
- [Ask AI with Context](./ASK_AI_CONTEXT.md) - Linked vs Global context search
- [Progress Report](./PROGRESS_REPORT.md) - Development milestones and achievements

---

## 📝 Conventions

### Status Tags
- ✅ Complete
- 🔜 Next / In progress
- 📋 Planned
- ⚠️ Blocked
- ❌ Cancelled

### File Naming
- `PHASE_N_PLAN.md` - Implementation plans
- `PHASE_N_RETROSPECTIVE.md` - Learnings
- `ARCHITECTURE_*.md` - Decisions
- `API_*.md` - API docs

---

**Last Updated**: Dec 24, 2025 (Phase 0 Complete)
**Next Update**: Jan 2, 2025 (Phase 1 Start)
**Version**: 0.1.0-alpha
