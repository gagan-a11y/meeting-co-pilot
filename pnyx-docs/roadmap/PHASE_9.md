# Phase 9: Calendar Integration & Workflow Automation

**Status:** **PLANNED**
**Focus:** Calendar-driven adoption, pre-meeting context, and post-meeting distribution
**Prerequisite:** Phase 8 (Polish & Production) must be complete.

---

## 1. Goal
Make Pnyx a default part of meetings by integrating with calendars. Automatically deliver the right context before a meeting starts and ensure consistent distribution of notes after it ends.

## 2. Problems Solved
*   **Adoption friction:** Users forget to start Pnyx or add it to the meeting.
*   **Missing context:** Agenda/description/attendees are scattered and not captured in Pnyx.
*   **Inconsistent sharing:** Summaries are posted late or not at all.
*   **Weak continuity:** Recurring meetings lose history and open actions.

## 3. Scope

### A. Provider Support
*   **target:** Google Calendar (G Suite) with OAuth.

### B. Audio-Enhanced Notes (Post-Meeting)
*   **Goal:** improve note quality by summarizing from audio + meeting context.
*   **Inputs:** audio recording, agenda/description, participants + roles, meeting type.
*   **Outputs:** structured summary, decisions, action items with owners.
*   **Policy:** default to transcript-only for low-impact meetings; use audio for high-stakes meetings.

### C. Pre-Meeting Automation
*   **T-2 minute reminder email** to host (optional to attendees) with:
    *   "Start Pnyx" call-to-action
    *   Setup checklist (mic, room, permissions)
*   **Event metadata ingestion:** title, agenda/description, attendees, location, meeting link, recurring series ID.
*   **Pre-meeting brief:** generate a structured brief from agenda/description.
*   **Skeleton notes template:** headings and expected decision points shown in Pnyx before start.

### D. Post-Meeting Distribution
*   **Recap email to all attendees** with Pnyx notes link.
*   Optional **calendar writeback** (summary/decisions/actions appended to event description) when enabled.

## 4. Execution Plan

### Workstream 1: OAuth + Permissions
*   Least-privilege scopes for calendar read and optional writeback.
*   Org-level and user-level toggles for:
    *   Reminders
    *   Attendee email policy
    *   Calendar writeback

### Workstream 2: Event Sync
*   Sync upcoming events for connected users.
*   Identify meetings with conferencing links (Meet/Zoom) and recurring series.

### Workstream 3: Reminder + Brief Generation
*   Scheduler to send T-2 minute reminder emails.
*   Convert agenda/description into structured note templates.

### Workstream 4: Post-Meeting Distribution
*   After meeting end, send recap email with notes link.
*   Optional writeback to event description.

### Workstream 5: Audio-Enhanced Notes
*   Add audio summarization job using Gemini audio input.
*   Merge audio summary with agenda/participant context.
*   Implement fallback to transcript-only summary.

## 5. Success Metrics
*   **Adoption:** % of meetings started via calendar reminder.
*   **Coverage:** % of meetings with pre-meeting brief generated.
*   **Sharing:** % of meetings where all attendees receive recap email.
*   **Engagement:** Open rate for reminder and recap emails.
*   **Notes Quality:** internal QA score uplift for audio-based summaries vs transcript-only.

## 6. Risks & Mitigations
*   **Privacy concerns:** Provide opt-out and minimal writeback by default.
*   **Calendar permissions friction:** Clear scope explanation and admin controls.
*   **Email fatigue:** Default to host-only reminders, optional attendee notifications.
*   **Audio cost/latency:** Only run audio summaries for flagged high-impact meetings.
