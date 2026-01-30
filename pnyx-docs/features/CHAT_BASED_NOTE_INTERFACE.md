# Chat-Based Note Interface (Dynamic Notes)

## Overview
This feature transitions the meeting notes from a static document to a dynamic, collaborative interface. Users will be able to refine, expand, and edit meeting summaries using natural language commands through a chat interface integrated directly with the notes view.

## Problem
Currently, meeting notes are generated once and then require manual editing (BlockNote). While manual editing is powerful, it is time-consuming. Users often want to say "elaborate on the marketing discussion" or "reformat the action items into a table" without manually typing everything.

## Proposed Solution
Introduce a "Refine with AI" chat sidebar or overlay in the Meeting Details page that specifically targets the notes content.

### Key Capabilities
- **Natural Language Editing**: "Add a section about the budget," "Summarize the last 5 minutes more deeply," or "Make the tone more formal."
- **Context-Aware Refinement**: The AI has access to both the full transcript and the current state of the notes.
- **Iterative Improvement**: Users can chat back and forth with the AI to get the notes exactly right.
- **Section-Specific Targeting**: (Optional) Allow users to highlight a section of the notes and ask the AI to "clean this up."

## Technical Architecture

### Frontend
- **Chat Component**: A dedicated chat input within the notes panel.
- **State Management**: The notes state (markdown/BlockNote JSON) must be syncable with the AI's output.
- **Streaming Updates**: AI suggestions should ideally stream into a "preview" or update the notes in real-time.

### Backend
- **New Endpoint**: `POST /refine-notes`
    - Payload: `{ meeting_id: string, current_notes: string, user_instruction: string }`
    - Response: Updated notes or a diff.
- **Prompt Engineering**: System prompts specifically tuned for "Note Refinement" rather than just "Summarization."
- **Context Handling**: Ensuring the AI doesn't lose existing manual edits when applying new refinements.

## UI/UX Design
- The notes page will feature a "Refine" button that opens a chat interface.
- Chat history for refinements should be preserved so users can see how the notes evolved.
- "Undo/Redo" for AI refinements to prevent accidental loss of good content.

## Implementation Phases
1. **Phase 1: Basic Refinement Chat**: Send instructions to backend, get back full updated notes.
2. **Phase 2: Streaming & Diffs**: Implement streaming updates for better UX.
3. **Phase 3: Targeted Refinement**: Allow highlighting sections to refine specific parts of the meeting notes.
