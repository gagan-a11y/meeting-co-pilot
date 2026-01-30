from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
from typing import Optional, List, Dict
import logging
import os
import struct
from dotenv import load_dotenv

# Load environment variables before importing local modules
load_dotenv()

from db import DatabaseManager
import json
import asyncio
from threading import Lock
from transcript_processor import TranscriptProcessor
import time
import uuid
from pathlib import Path
import aiofiles
from datetime import datetime

from fastapi import Depends, status
from auth import get_current_user, User
from rbac import RBAC

# Audio recording and diarization imports
from audio_recorder import (
    AudioRecorder,
    get_or_create_recorder,
    stop_recorder,
    active_recorders,
)
from diarization import DiarizationService, get_diarization_service, DiarizationResult
from file_processing import get_file_processor

# Configure logger with line numbers and function names
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create console handler with formatting
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create formatter with line numbers and function names
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
console_handler.setFormatter(formatter)

# Add handler to logger if not already added
if not logger.handlers:
    logger.addHandler(console_handler)

app = FastAPI(
    title="Meeting Summarizer API",
    description="API for processing and summarizing meeting transcripts",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3118",
        "http://localhost:3000",
        "https://pnyxx.vercel.app",
        "https://meet.digest.lat",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Global database manager instance for meeting management endpoints
db = DatabaseManager()
rbac = RBAC(db)


# New Pydantic models for meeting management
class Transcript(BaseModel):
    id: str
    text: str
    timestamp: str
    # Recording-relative timestamps for audio-transcript synchronization
    audio_start_time: Optional[float] = None
    audio_end_time: Optional[float] = None
    duration: Optional[float] = None


class MeetingResponse(BaseModel):
    id: str
    title: str


class MeetingDetailsResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    transcripts: List[Transcript]


class MeetingTitleUpdate(BaseModel):
    meeting_id: str
    title: str


class DeleteMeetingRequest(BaseModel):
    meeting_id: str


class SaveTranscriptRequest(BaseModel):
    meeting_title: str
    transcripts: List[Transcript]
    folder_path: Optional[str] = None
    template_id: Optional[str] = "standard_meeting"
    session_id: Optional[str] = None  # NEW: For linking audio recording


class SaveModelConfigRequest(BaseModel):
    provider: str
    model: str
    whisperModel: str
    apiKey: Optional[str] = None


class SaveTranscriptConfigRequest(BaseModel):
    provider: str
    model: str
    apiKey: Optional[str] = None


class TranscriptRequest(BaseModel):
    """Request model for transcript text, updated with meeting_id"""

    text: str
    model: str
    model_name: str
    meeting_id: str
    chunk_size: Optional[int] = 5000
    overlap: Optional[int] = 1000
    custom_prompt: Optional[str] = "Generate a summary of the meeting transcript."
    templateId: Optional[str] = "standard_meeting"  # Template for note generation


class ChatRequest(BaseModel):
    meeting_id: str
    question: str
    model: str
    model_name: str
    context_text: Optional[str] = None
    allowed_meeting_ids: Optional[List[str]] = None  # Scoped search
    history: Optional[List[Dict[str, str]]] = None  # Conversation history


class CatchUpRequest(BaseModel):
    """Request model for catch-up summary"""

    transcripts: List[str]  # Current transcripts as list of strings
    model: str = "gemini"
    model_name: str = "gemini-2.0-flash"


class SearchContextRequest(BaseModel):
    """Request model for cross-meeting context search"""

    query: str
    n_results: int = 5
    allowed_meeting_ids: Optional[List[str]] = None  # None = search all meetings


class GenerateNotesRequest(BaseModel):
    """Request model for generating detailed meeting notes."""

    meeting_id: str
    template_id: str = "standard_meeting"
    model: str = "gemini"
    model_name: str = "gemini-2.0-flash"
    custom_context: str = ""  # User-provided context for better note generation


class RefineNotesRequest(BaseModel):
    """Request model for refining meeting notes."""

    meeting_id: str
    current_notes: str
    user_instruction: str
    model: str = "gemini"
    model_name: str = "gemini-2.0-flash"


# ============================================
# Diarization Request/Response Models
# ============================================


class DiarizeRequest(BaseModel):
    """Request model for triggering speaker diarization."""

    provider: str = "deepgram"  # 'deepgram' or 'assemblyai'


class RenameSpeakerRequest(BaseModel):
    """Request model for renaming a speaker label."""

    display_name: str


class DiarizationStatusResponse(BaseModel):
    """Response model for diarization status."""

    meeting_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed', 'not_recorded'
    speaker_count: Optional[int] = None
    provider: Optional[str] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None


class SpeakerMappingItem(BaseModel):
    """Represents a single speaker mapping entry."""

    label: str
    display_name: str
    color: Optional[str] = None


class SpeakerMappingResponse(BaseModel):
    """Response model for speaker label mappings."""

    meeting_id: str
    speakers: List[SpeakerMappingItem]


class SummaryProcessor:
    """Handles the processing of summaries in a thread-safe way"""

    def __init__(self):
        try:
            self.db = DatabaseManager()

            logger.info("Initializing SummaryProcessor components")
            self.transcript_processor = TranscriptProcessor()
            logger.info("SummaryProcessor initialized successfully (core components)")
        except Exception as e:
            logger.error(
                f"Failed to initialize SummaryProcessor: {str(e)}", exc_info=True
            )
            raise

    async def process_transcript(
        self,
        text: str,
        model: str = "gemini",
        model_name: str = "gemini-2.0-flash",
        chunk_size: int = 5000,
        overlap: int = 1000,
        custom_prompt: str = "Generate a summary of the meeting transcript.",
    ) -> tuple:
        """Process a transcript text"""
        try:
            if not text:
                raise ValueError("Empty transcript text provided")

            # Validate chunk_size and overlap
            if chunk_size <= 0:
                raise ValueError("chunk_size must be positive")
            if overlap < 0:
                raise ValueError("overlap must be non-negative")
            if overlap >= chunk_size:
                overlap = chunk_size - 1  # Ensure overlap is less than chunk_size

            # Ensure step size is positive
            step_size = chunk_size - overlap
            if step_size <= 0:
                chunk_size = overlap + 1  # Adjust chunk_size to ensure positive step

            logger.info(
                f"Processing transcript of length {len(text)} with chunk_size={chunk_size}, overlap={overlap}"
            )
            (
                num_chunks,
                all_json_data,
            ) = await self.transcript_processor.process_transcript(
                text=text,
                model=model,
                model_name=model_name,
                chunk_size=chunk_size,
                overlap=overlap,
                custom_prompt=custom_prompt,
            )
            logger.info(f"Successfully processed transcript into {num_chunks} chunks")

            return num_chunks, all_json_data
        except Exception as e:
            logger.error(f"Error processing transcript: {str(e)}", exc_info=True)
            raise

    def cleanup(self):
        """Cleanup resources"""
        try:
            logger.info("Cleaning up resources")
            if hasattr(self, "transcript_processor"):
                self.transcript_processor.cleanup()
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)


# Initialize processor
processor = SummaryProcessor()


# New meeting management endpoints
@app.get("/get-meetings", response_model=List[MeetingResponse])
async def get_meetings(current_user: User = Depends(get_current_user)):
    """Get all meetings visible to the current user"""
    try:
        # Get authorized meeting IDs
        accessible_ids = await rbac.get_accessible_meetings(current_user)

        # Get all meetings (TODO: optimize to fetch only accessible in SQL)
        meetings = await db.get_all_meetings()

        # Filter
        visible_meetings = [m for m in meetings if m["id"] in accessible_ids]

        return [
            {"id": meeting["id"], "title": meeting["title"]}
            for meeting in visible_meetings
        ]
    except Exception as e:
        logger.error(f"Error getting meetings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-meeting/{meeting_id}", response_model=MeetingDetailsResponse)
async def get_meeting(meeting_id: str, current_user: User = Depends(get_current_user)):
    """Get a specific meeting by ID with all its details"""
    # Permission Check
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        meeting = await db.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return meeting
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting meeting: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/save-meeting-title")
async def save_meeting_title(
    data: MeetingTitleUpdate, current_user: User = Depends(get_current_user)
):
    """Save a meeting title"""
    if not await rbac.can(current_user, "edit", data.meeting_id):
        raise HTTPException(
            status_code=403, detail="Permission denied to edit this meeting"
        )

    try:
        await db.update_meeting_title(data.meeting_id, data.title)
        return {"message": "Meeting title saved successfully"}
    except Exception as e:
        logger.error(f"Error saving meeting title: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/delete-meeting")
async def delete_meeting(
    data: DeleteMeetingRequest, current_user: User = Depends(get_current_user)
):
    """Delete a meeting and all its associated data"""
    # Note: Only OWNER (and maybe workspace admin) can delete.
    # Security logic handles this check.
    if not await rbac.can(current_user, "delete", data.meeting_id):
        raise HTTPException(
            status_code=403, detail="Permission denied to delete this meeting"
        )

    try:
        success = await db.delete_meeting(data.meeting_id)
        if success:
            return {"message": "Meeting deleted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete meeting")
    except Exception as e:
        logger.error(f"Error deleting meeting: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class SaveSummaryRequest(BaseModel):
    meeting_id: str
    summary: dict


@app.post("/save-summary")
async def save_summary(
    data: SaveSummaryRequest, current_user: User = Depends(get_current_user)
):
    """Save or update meeting summary/notes"""
    if not await rbac.can(current_user, "edit", data.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to edit summary")

    try:
        logger.info(f"Saving summary for meeting {data.meeting_id}")

        # Update the summary_processes table with the new content
        await processor.db.update_process(
            meeting_id=data.meeting_id, status="completed", result=data.summary
        )

        logger.info(f"Successfully saved summary for meeting {data.meeting_id}")
        return {"message": "Summary saved successfully"}
    except Exception as e:
        logger.error(f"Error saving summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def process_transcript_background(
    process_id: str,
    transcript: TranscriptRequest,
    custom_prompt: str,
    user_email: Optional[str] = None,
):
    """Background task to process transcript"""
    try:
        logger.info(f"Starting background processing for process_id: {process_id}")

        # Early validation for common issues
        if not transcript.text or not transcript.text.strip():
            raise ValueError("Empty transcript text provided")

        if transcript.model in ["claude", "groq", "openai", "gemini"]:
            # Check if API key is available for cloud providers
            api_key = await processor.db.get_api_key(
                transcript.model, user_email=user_email
            )
            if not api_key:
                # Check for env var fallbacks
                import os

                if transcript.model == "gemini" and (
                    os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                ):
                    pass
                else:
                    provider_names = {
                        "claude": "Anthropic",
                        "groq": "Groq",
                        "openai": "OpenAI",
                        "gemini": "Gemini",
                    }
                    raise ValueError(
                        f"{provider_names.get(transcript.model, transcript.model)} API key not configured. Please set your API key in the model settings."
                    )

        # Use template-specific prompt if templateId is provided
        template_prompt = custom_prompt
        template_id = getattr(transcript, "templateId", None) or getattr(
            transcript, "template_id", None
        )
        if template_id:
            template_prompt = get_template_prompt(template_id)

        _, all_json_data = await processor.process_transcript(
            text=transcript.text,
            model=transcript.model,
            model_name=transcript.model_name,
            chunk_size=transcript.chunk_size,
            overlap=transcript.overlap,
            custom_prompt=template_prompt,
            user_email=user_email,
        )

        # Create final summary structure by aggregating chunk results
        final_summary = {
            "MeetingName": "",
            "People": {"title": "People", "blocks": []},
            "SessionSummary": {"title": "Session Summary", "blocks": []},
            "CriticalDeadlines": {"title": "Critical Deadlines", "blocks": []},
            "KeyItemsDecisions": {"title": "Key Items & Decisions", "blocks": []},
            "ImmediateActionItems": {"title": "Immediate Action Items", "blocks": []},
            "NextSteps": {"title": "Next Steps", "blocks": []},
            # "OtherImportantPoints": {"title": "Other Important Points", "blocks": []},
            # "ClosingRemarks": {"title": "Closing Remarks", "blocks": []},
            "MeetingNotes": {"meeting_name": "", "sections": []},
        }

        # Process each chunk's data
        for json_str in all_json_data:
            try:
                json_dict = json.loads(json_str)
                if "MeetingName" in json_dict and json_dict["MeetingName"]:
                    final_summary["MeetingName"] = json_dict["MeetingName"]
                for key in final_summary:
                    if key == "MeetingNotes" and key in json_dict:
                        # Handle MeetingNotes sections
                        if isinstance(json_dict[key].get("sections"), list):
                            # Ensure each section has blocks array
                            for section in json_dict[key]["sections"]:
                                if not section.get("blocks"):
                                    section["blocks"] = []
                            final_summary[key]["sections"].extend(
                                json_dict[key]["sections"]
                            )
                        if json_dict[key].get("meeting_name"):
                            final_summary[key]["meeting_name"] = json_dict[key][
                                "meeting_name"
                            ]
                    elif (
                        key != "MeetingName"
                        and key in json_dict
                        and isinstance(json_dict[key], dict)
                        and "blocks" in json_dict[key]
                    ):
                        if isinstance(json_dict[key]["blocks"], list):
                            final_summary[key]["blocks"].extend(
                                json_dict[key]["blocks"]
                            )
                            # Also add as a new section in MeetingNotes if not already present
                            section_exists = False
                            for section in final_summary["MeetingNotes"]["sections"]:
                                if section["title"] == json_dict[key]["title"]:
                                    section["blocks"].extend(json_dict[key]["blocks"])
                                    section_exists = True
                                    break

                            if not section_exists:
                                final_summary["MeetingNotes"]["sections"].append(
                                    {
                                        "title": json_dict[key]["title"],
                                        "blocks": json_dict[key]["blocks"].copy()
                                        if json_dict[key]["blocks"]
                                        else [],
                                    }
                                )
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse JSON chunk for {process_id}: {e}. Chunk: {json_str[:100]}..."
                )
            except Exception as e:
                logger.error(
                    f"Error processing chunk data for {process_id}: {e}. Chunk: {json_str[:100]}..."
                )

        # Update database with meeting name using meeting_id
        if final_summary["MeetingName"]:
            await processor.db.update_meeting_name(
                transcript.meeting_id, final_summary["MeetingName"]
            )

        # Store embeddings for cross-meeting search
        # NOTE: Vector DB usage temporarily disabled (Jan 30, 2026)
        # try:
        #     from vector_store import store_meeting_embeddings
        #
        #     # Use chunks from the transcript text
        #     transcript_dicts = [
        #         {"text": transcript.text, "timestamp": datetime.now().isoformat()}
        #     ]
        #     chunks_stored = await store_meeting_embeddings(
        #         meeting_id=transcript.meeting_id,
        #         meeting_title=final_summary.get("MeetingName") or "Uploaded Transcript",
        #         meeting_date=datetime.now().isoformat(),
        #         transcripts=transcript_dicts,
        #     )
        #     logger.info(
        #         f"✅ Stored {chunks_stored} embedding chunks for cross-meeting search"
        #     )
        # except Exception as e:
        #     logger.warning(f"⚠️ Failed to store embeddings (non-critical): {e}")

        # Save final result
        if all_json_data:
            await processor.db.update_process(
                process_id, status="completed", result=final_summary
            )
            logger.info(f"Background processing completed for process_id: {process_id}")

        else:
            error_msg = "Summary generation failed: No chunks were processed successfully. Check logs for specific errors."
            await processor.db.update_process(
                process_id, status="failed", error=error_msg
            )
            logger.error(
                f"Background processing failed for process_id: {process_id} - {error_msg}"
            )

    except ValueError as e:
        # Handle specific value errors (like API key issues)
        error_msg = str(e)
        logger.error(
            f"Configuration error in background processing for {process_id}: {error_msg}",
            exc_info=True,
        )
        try:
            await processor.db.update_process(
                process_id, status="failed", error=error_msg
            )
        except Exception as db_e:
            logger.error(
                f"Failed to update DB status to failed for {process_id}: {db_e}",
                exc_info=True,
            )
    except Exception as e:
        # Handle all other exceptions
        error_msg = f"Processing error: {str(e)}"
        logger.error(
            f"Error in background processing for {process_id}: {error_msg}",
            exc_info=True,
        )
        try:
            await processor.db.update_process(
                process_id, status="failed", error=error_msg
            )
        except Exception as db_e:
            logger.error(
                f"Failed to update DB status to failed for {process_id}: {db_e}",
                exc_info=True,
            )


@app.post("/process-transcript")
async def process_transcript_api(
    transcript: TranscriptRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Process a transcript text with background processing"""
    try:
        # 0. Ensure meeting exists and check permissions
        meeting = await db.get_meeting(transcript.meeting_id)
        if not meeting:
            # New Meeting: Claim Ownership
            await db.save_meeting(
                meeting_id=transcript.meeting_id,
                title="Untitled Meeting",  # Default title
                owner_id=current_user.email,
                workspace_id=None,  # Defaults to Personal
            )
            logger.info(
                f"Created new meeting {transcript.meeting_id} for owner {current_user.email}"
            )
        else:
            # Existing Meeting: Check Edit Permission
            if not await rbac.can(current_user, "edit", transcript.meeting_id):
                raise HTTPException(
                    status_code=403, detail="Permission denied to edit this meeting"
                )

        # Create new process linked to meeting_id
        process_id = await processor.db.create_process(transcript.meeting_id)

        # Save transcript data associated with meeting_id
        await processor.db.save_transcript(
            transcript.meeting_id,
            transcript.text,
            transcript.model,
            transcript.model_name,
            transcript.chunk_size,
            transcript.overlap,
        )

        # Use template-specific prompt if templateId is provided, otherwise use custom_prompt
        custom_prompt = transcript.custom_prompt
        if (
            hasattr(transcript, "templateId")
            and transcript.templateId
            and not custom_prompt
        ):
            custom_prompt = get_template_prompt(transcript.templateId)

        # Start background processing
        background_tasks.add_task(
            process_transcript_background,
            process_id,
            transcript,
            custom_prompt,
            current_user.email,
        )

        return JSONResponse({"message": "Processing started", "process_id": process_id})

    except Exception as e:
        logger.error(f"Error in process_transcript_api: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-detailed-notes")
async def generate_detailed_notes(
    request: GenerateNotesRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """
    Generates detailed meeting notes using Gemini, saves them, and returns the result.
    This is intended for automatic, high-quality note generation post-meeting.
    Uses templates for structured output based on meeting type.
    """
    try:
        if not await rbac.can(current_user, "ai_interact", request.meeting_id):
            raise HTTPException(
                status_code=403, detail="Permission denied to generate notes"
            )

        logger.info(
            f"Generating detailed notes for meeting {request.meeting_id} using template {request.template_id}"
        )

        # 1. Fetch meeting transcripts from the database
        meeting_data = await db.get_meeting(request.meeting_id)
        if not meeting_data or not meeting_data.get("transcripts"):
            raise HTTPException(
                status_code=404, detail="Meeting or transcripts not found."
            )

        transcripts = meeting_data["transcripts"]

        # Check if we have speaker info
        has_speakers = any(t.get("speaker") for t in transcripts)
        if has_speakers:
            diarization_service = get_diarization_service()
            full_transcript_text = diarization_service.format_transcript_with_speakers(
                transcripts
            )
        else:
            full_transcript_text = "\n".join([t["text"] for t in transcripts])

        if not full_transcript_text.strip():
            raise HTTPException(status_code=400, detail="Transcript text is empty.")

        meeting_title = meeting_data.get("title", "Untitled Meeting")

        # 2. Start background processing (non-blocking)
        background_tasks.add_task(
            generate_notes_with_gemini_background,
            request.meeting_id,
            full_transcript_text,
            request.template_id,
            meeting_title,
            "",  # custom_context
            current_user.email,
        )

        return JSONResponse(
            content={
                "message": "Notes generation started",
                "meeting_id": request.meeting_id,
                "template_id": request.template_id,
                "status": "processing",
            }
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error starting notes generation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/meetings/{meeting_id}/generate-notes")
async def generate_notes_for_meeting(
    meeting_id: str,
    request: GenerateNotesRequest = None,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
):
    """
    Generate meeting notes for a specific meeting using the selected template.
    This endpoint is designed to be called from the Meeting Details page.

    Path Parameters:
        meeting_id: The ID of the meeting to generate notes for

    Body Parameters (optional):
        template_id: The template to use for note generation (default: standard_meeting)
        model: The AI model provider (default: gemini)
        model_name: The specific model name (default: gemini-2.0-flash)
    """
    if not await rbac.can(current_user, "ai_interact", meeting_id):
        raise HTTPException(
            status_code=403, detail="Permission denied to generate notes"
        )

    try:
        # Use path parameter if no request body provided
        actual_meeting_id = meeting_id
        template_id = "standard_meeting"
        model_name = "gemini-2.0-flash"
        custom_context = ""

        if request:
            template_id = request.template_id or "standard_meeting"
            model_name = request.model_name or "gemini-2.0-flash"
            custom_context = request.custom_context or ""
            # If request has meeting_id, use path param anyway for consistency

        logger.info(
            f"Generating notes for meeting {actual_meeting_id} using template {template_id}"
        )

        # 1. Fetch meeting transcripts from the database
        meeting_data = await db.get_meeting(actual_meeting_id)
        if not meeting_data or not meeting_data.get("transcripts"):
            raise HTTPException(
                status_code=404, detail="Meeting or transcripts not found."
            )

        transcripts = meeting_data["transcripts"]

        # Check if we have speaker info
        has_speakers = any(t.get("speaker") for t in transcripts)
        if has_speakers:
            diarization_service = get_diarization_service()
            full_transcript_text = diarization_service.format_transcript_with_speakers(
                transcripts
            )
        else:
            full_transcript_text = "\n".join([t["text"] for t in transcripts])

        if not full_transcript_text.strip():
            raise HTTPException(status_code=400, detail="Transcript text is empty.")

        meeting_title = meeting_data.get("title", "Untitled Meeting")

        # 2. Start background processing (non-blocking)
        background_tasks.add_task(
            generate_notes_with_gemini_background,
            actual_meeting_id,
            full_transcript_text,
            template_id,
            meeting_title,
            custom_context,
            current_user.email,
        )

        return JSONResponse(
            content={
                "message": "Notes generation started",
                "meeting_id": actual_meeting_id,
                "template_id": template_id,
                "status": "processing",
            }
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(
            f"Error starting notes generation for meeting {meeting_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat-meeting")
async def chat_meeting(
    request: ChatRequest, current_user: User = Depends(get_current_user)
):
    """
    Chat with a specific meeting using AI.
    Streams the response back to the client.
    """
    if not await rbac.can(current_user, "ai_interact", request.meeting_id):
        raise HTTPException(
            status_code=403, detail="Permission denied to chat with this meeting"
        )

    try:
        logger.info(f"Received chat request for meeting {request.meeting_id}")
        logger.info(f"Allowed meeting IDs: {request.allowed_meeting_ids}")
        logger.info(f"History length: {len(request.history) if request.history else 0}")

        # 1. Get current meeting context (real-time)
        full_text = ""
        # 1. Get current meeting context (real-time)
        full_text = ""
        # FIX: Check for uniqueness of context_text (if provided, use it, even if empty string)
        if request.context_text is not None:
            full_text = request.context_text
            logger.info("Using provided context_text for chat")
        else:
            # Get meeting data from DB only if meeting_id is likely valid (not "current-recording")
            # But simpler to just try fetching if context wasn't provided
            meeting_data = await db.get_meeting(request.meeting_id)
            if meeting_data:
                # Construct context from transcripts
                transcripts = meeting_data.get("transcripts", [])
                if not transcripts:
                    # Try getting from transcript_chunks if individual transcripts are empty (fallback)
                    chunk_data = await db.get_transcript_data(request.meeting_id)
                    if chunk_data and chunk_data.get("transcript"):
                        full_text = chunk_data.get("transcript")
                    elif chunk_data and chunk_data.get("transcript_text"):
                        full_text = chunk_data.get("transcript_text")
                else:
                    # Join all transcript segments
                    full_text = "\n".join([t["text"] for t in transcripts])
            else:
                # If meeting not found in DB and no context provided, we just have empty context.
                # We don't 404 here because the user might just want to chat with history/other meetings.
                logger.warning(
                    f"Meeting {request.meeting_id} not found in DB and no context provided."
                )

        # FIX: Allow proceeding if we have cross-meeting context (allowed_meeting_ids) OR if it's a general question
        # The prompt will handle empty context.
        if not full_text and not request.allowed_meeting_ids and not request.history:
            # Only block if we truly have NOTHING to go on (no context, no linked search, no history)
            # But actually, users might just want to say "Hi". So we should arguably always allow it.
            # However, to preserve original intent of "No transcript", we'll keep it soft.
            logger.info(
                "No context, history, or linked meetings. Proceeding with empty context."
            )

        # 3. Stream response using TranscriptProcessor
        stream_generator = await processor.transcript_processor.chat_about_meeting(
            context=full_text,
            question=request.question,
            model=request.model,
            model_name=request.model_name,
            allowed_meeting_ids=request.allowed_meeting_ids,
            history=request.history,
            user_email=current_user.email,
        )

        return StreamingResponse(stream_generator, media_type="text/plain")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat_meeting: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/catch-up")
async def catch_up(
    request: CatchUpRequest, current_user: User = Depends(get_current_user)
):
    """
    Generate a quick bulleted summary of the meeting so far.
    For late joiners or participants who zoned out.
    Streams the response back for fast display.
    """
    try:
        logger.info(
            f"Catch-up request received with {len(request.transcripts)} transcripts"
        )

        # Join all transcripts
        full_text = "\n".join(request.transcripts)

        if not full_text or len(full_text.strip()) < 10:
            return JSONResponse(
                status_code=400,
                content={"error": "Not enough transcript content to summarize yet."},
            )

        # Create catch-up prompt
        catch_up_prompt = f"""You are a meeting assistant. A participant just joined late or zoned out and needs a quick catch-up.

Based on the meeting transcript below, provide a BRIEF bulleted summary of:
• Key topics discussed
• Important decisions made
• Action items mentioned
• Any deadlines or dates mentioned

Keep it SHORT (max 5-7 bullets). Start each bullet with "•".
Be conversational: "The team discussed..." not "Discussion of..."

Meeting Transcript:
---
{full_text}
---

Quick Catch-Up Summary:"""

        # Stream response using Groq for speed
        async def generate_catch_up():
            try:
                if request.model == "groq":
                    api_key = await db.get_api_key(
                        "groq", user_email=current_user.email
                    )
                    if not api_key:
                        import os

                        api_key = os.getenv("GROQ_API_KEY")
                    if not api_key:
                        yield "Error: Groq API key not configured"
                        return

                    from groq import AsyncGroq

                    client = AsyncGroq(api_key=api_key)

                    stream = await client.chat.completions.create(
                        messages=[{"role": "user", "content": catch_up_prompt}],
                        model=request.model_name,
                        stream=True,
                        max_tokens=500,  # Keep it short
                        temperature=0.3,  # More focused
                    )

                    async for chunk in stream:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            yield content
                elif request.model == "gemini":
                    api_key = await db.get_api_key(
                        "gemini", user_email=current_user.email
                    )
                    if not api_key:
                        import os

                        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv(
                            "GEMINI_API_KEY"
                        )
                    if not api_key:
                        yield "Error: Gemini API key not configured"
                        return

                    import google.generativeai as genai

                    genai.configure(api_key=api_key)

                    # Ensure properly named model
                    model_name = request.model_name
                    if not model_name.startswith("gemini-"):
                        model_name = (
                            f"gemini-{model_name}"
                            if "gemini" not in model_name
                            else model_name
                        )

                    try:
                        model = genai.GenerativeModel(model_name)
                        response = model.generate_content(catch_up_prompt, stream=True)

                        for chunk in response:
                            if chunk.text:
                                yield chunk.text
                    except Exception as e:
                        logger.error(f"Gemini generation error: {e}")
                        yield f"Error generating summary with Gemini: {str(e)}"

                else:
                    yield f"Error: Only Groq and Gemini models are currently supported for catch-up (requested: {request.model})"

            except Exception as e:
                logger.error(f"Error generating catch-up: {e}", exc_info=True)
                yield f"\n\nError: {str(e)}"

        return StreamingResponse(generate_catch_up(), media_type="text/plain")

    except Exception as e:
        logger.error(f"Error in catch_up: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/refine-notes")
async def refine_notes(
    request: RefineNotesRequest, current_user: User = Depends(get_current_user)
):
    """
    Refine existing meeting notes based on user instructions and transcript context.
    Streams the refined notes back.
    """
    if not await rbac.can(current_user, "ai_interact", request.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to refine notes")

    try:
        logger.info(
            f"Refining notes for meeting {request.meeting_id} with instruction: {request.user_instruction[:50]}..."
        )

        # 1. Fetch meeting transcripts for context
        meeting_data = await db.get_meeting(request.meeting_id)
        full_transcript = ""
        if meeting_data and meeting_data.get("transcripts"):
            full_transcript = "\n".join(
                [t["text"] for t in meeting_data["transcripts"]]
            )

        # 2. Construct Prompt
        refine_prompt = f"""You are an expert meeting notes editor.
Your task is to REFINE the Current Meeting Notes based strictly on the User Instruction and the provided Context (Transcript).

Context (Meeting Transcript):
---
{full_transcript[:30000]} {(len(full_transcript) > 30000) and "...(truncated)" or ""}
---

Current Meeting Notes:
---
{request.current_notes}
---

User Instruction: {request.user_instruction}

Guidelines:
1. You MUST start your response with a detailed bulleted list of changes made (e.g., "Fixed typo in 'deadline' (was 'dealine')", "Changed tone of 'Next Steps' to be more formal").
2. You MUST then output exactly: "|||SEPARATOR|||" (without quotes).
3. After the separator, provide the FULL updated notes content.
4. Do NOT wrap the output in markdown code blocks like ```markdown ... ```.
5. The content after the separator must be the direct markdown content of the notes.
6. Use the Transcript to ensure accuracy if adding details.

Strict Output Structure:
[Detailed bulleted list of changes]
|||SEPARATOR|||
[Full Updated Notes Markdown Content]"""

        # 3. Stream Response (similar to catch_up)
        async def generate_refinement():
            try:
                if request.model == "groq":
                    api_key = await db.get_api_key(
                        "groq", user_email=current_user.email
                    )
                    if not api_key:
                        import os

                        api_key = os.getenv("GROQ_API_KEY")
                    if not api_key:
                        yield "Error: Groq API key not configured"
                        return

                    from groq import AsyncGroq

                    client = AsyncGroq(api_key=api_key)

                    stream = await client.chat.completions.create(
                        messages=[{"role": "user", "content": refine_prompt}],
                        model=request.model_name,
                        stream=True,
                        max_tokens=2000,
                        temperature=0.3,
                    )

                    async for chunk in stream:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            yield content

                elif request.model == "gemini":
                    api_key = await db.get_api_key(
                        "gemini", user_email=current_user.email
                    )
                    if not api_key:
                        import os

                        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv(
                            "GEMINI_API_KEY"
                        )
                    if not api_key:
                        yield "Error: Gemini API key not configured"
                        return

                    import google.generativeai as genai

                    genai.configure(api_key=api_key)

                    # Ensure properly named model
                    model_name = request.model_name
                    if not model_name.startswith("gemini-"):
                        model_name = (
                            f"gemini-{model_name}"
                            if "gemini" not in model_name
                            else model_name
                        )

                    try:
                        model = genai.GenerativeModel(model_name)
                        response = model.generate_content(refine_prompt, stream=True)

                        for chunk in response:
                            if chunk.text:
                                yield chunk.text
                    except Exception as e:
                        logger.error(f"Gemini generation error: {e}")
                        yield f"Error generating refinement with Gemini: {str(e)}"
                else:
                    yield f"Error: Model {request.model} not supported for refinement yet."

            except Exception as e:
                logger.error(f"Error generating refinement: {e}", exc_info=True)
                yield f"Error: {str(e)}"

        return StreamingResponse(generate_refinement(), media_type="text/plain")

    except Exception as e:
        logger.error(f"Error in refine_notes: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search-context")
async def search_context_endpoint(request: SearchContextRequest):
    """
    Search across past meetings for relevant context.
    Returns matching chunks with source citations.
    """
    try:
        # NOTE: Vector DB usage temporarily disabled (Jan 30, 2026)
        # Use SQL search (db.search_transcripts) or return empty if vector search is strictly required

        # from vector_store import search_context, get_collection_stats

        # # Check if vector store is available
        # stats = get_collection_stats()
        # if stats.get("status") != "available":
        #     return JSONResponse(
        #         status_code=503,
        #         content={"error": "Vector store not available", "results": []},
        #     )

        # # Perform search
        # results = await search_context(
        #     query=request.query,
        #     n_results=request.n_results,
        #     allowed_meeting_ids=request.allowed_meeting_ids,
        # )

        # Fallback to empty results for now
        results = []
        # Optional: could call await db.search_transcripts(request.query) if we wanted text fallback

        return {
            "status": "success",
            "query": request.query,
            "results": results,
            "total_indexed": 0,  # stats.get("count", 0),
        }

    except Exception as e:
        logger.error(f"Error in search_context: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-summary/{meeting_id}")
async def get_summary(meeting_id: str, current_user: User = Depends(get_current_user)):
    """Get the summary for a given meeting ID"""
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        result = await processor.db.get_transcript_data(meeting_id)
        if not result:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "meetingName": None,
                    "meeting_id": meeting_id,
                    "data": None,
                    "start": None,
                    "end": None,
                    "error": "Meeting ID not found",
                },
            )

        status = result.get("status", "unknown").lower()
        logger.debug(
            f"Summary status for meeting {meeting_id}: {status}, error: {result.get('error')}"
        )

        # Parse result data if available
        summary_data = None
        if result.get("result"):
            try:
                # Check if result is already a dict (handled by asyncpg jsonb)
                if isinstance(result["result"], dict):
                    summary_data = result["result"]
                else:
                    # Otherwise parse string
                    parsed_result = json.loads(result["result"])
                    if isinstance(parsed_result, str):
                        summary_data = json.loads(parsed_result)
                    else:
                        summary_data = parsed_result

                if not isinstance(summary_data, dict):
                    logger.error(
                        f"Parsed summary data is not a dictionary for meeting {meeting_id}"
                    )
                    summary_data = None
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse JSON data for meeting {meeting_id}: {str(e)}"
                )
                status = "failed"
                result["error"] = f"Invalid summary data format: {str(e)}"
            except Exception as e:
                logger.error(
                    f"Unexpected error parsing summary data for {meeting_id}: {str(e)}"
                )
                status = "failed"
                result["error"] = f"Error processing summary data: {str(e)}"

        # Transform summary data into frontend format if available - PRESERVE ORDER
        transformed_data = {}
        if isinstance(summary_data, dict) and status == "completed":
            # Add MeetingName to transformed data
            transformed_data["MeetingName"] = summary_data.get("MeetingName", "")

            # Pass through markdown format if present (new notes generation flow)
            if "markdown" in summary_data:
                transformed_data["markdown"] = summary_data["markdown"]
                logger.info(
                    f"Passing through markdown content for meeting {meeting_id}"
                )

            # Map backend sections to frontend sections
            section_mapping = {
                # "SessionSummary": "key_points",
                # "ImmediateActionItems": "action_items",
                # "KeyItemsDecisions": "decisions",
                # "NextSteps": "next_steps",
                # "CriticalDeadlines": "critical_deadlines",
                # "People": "people"
            }

            # Add each section to transformed data
            for backend_key, frontend_key in section_mapping.items():
                if backend_key in summary_data and isinstance(
                    summary_data[backend_key], dict
                ):
                    transformed_data[frontend_key] = summary_data[backend_key]

            # Add meeting notes sections if available - PRESERVE ORDER AND HANDLE DUPLICATES
            if "MeetingNotes" in summary_data and isinstance(
                summary_data["MeetingNotes"], dict
            ):
                meeting_notes = summary_data["MeetingNotes"]
                if isinstance(meeting_notes.get("sections"), list):
                    # Add section order array to maintain order
                    transformed_data["_section_order"] = []
                    used_keys = set()

                    for index, section in enumerate(meeting_notes["sections"]):
                        if (
                            isinstance(section, dict)
                            and "title" in section
                            and "blocks" in section
                        ):
                            # Ensure blocks is a list to prevent frontend errors
                            if not isinstance(section.get("blocks"), list):
                                section["blocks"] = []

                            # Convert title to snake_case key
                            base_key = (
                                section["title"]
                                .lower()
                                .replace(" & ", "_")
                                .replace(" ", "_")
                            )

                            # Handle duplicate section names by adding index
                            key = base_key
                            if key in used_keys:
                                key = f"{base_key}_{index}"

                            used_keys.add(key)
                            transformed_data[key] = section
                            # Only add to _section_order if the section was successfully added
                            transformed_data["_section_order"].append(key)

        # Helper to safely serialize datetime
        def serialize_dt(dt):
            if isinstance(dt, datetime):
                return dt.isoformat()
            return dt

        response = {
            "status": "processing"
            if status in ["processing", "pending", "started"]
            else status,
            "meetingName": summary_data.get("MeetingName")
            if isinstance(summary_data, dict)
            else None,
            "meeting_id": meeting_id,
            "start": serialize_dt(result.get("start_time")),
            "end": serialize_dt(result.get("end_time")),
            "data": transformed_data if status == "completed" else None,
        }

        if status == "failed":
            response["status"] = "error"
            response["error"] = result.get("error", "Unknown processing error")
            response["data"] = None
            response["meetingName"] = None
            logger.info(f"Returning failed status with error: {response['error']}")
            return JSONResponse(status_code=400, content=response)

        elif status in ["processing", "pending", "started"]:
            response["data"] = None
            return JSONResponse(status_code=202, content=response)

        elif status == "completed":
            if not summary_data:
                response["status"] = "error"
                response["error"] = "Completed but summary data is missing or invalid"
                response["data"] = None
                response["meetingName"] = None
                return JSONResponse(status_code=500, content=response)
            return JSONResponse(status_code=200, content=response)

        else:
            response["status"] = "error"
            response["error"] = f"Unknown or unexpected status: {status}"
            response["data"] = None
            response["meetingName"] = None
            return JSONResponse(status_code=500, content=response)

    except Exception as e:
        logger.error(f"Error getting summary for {meeting_id}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "meetingName": None,
                "meeting_id": meeting_id,
                "data": None,
                "start": None,
                "end": None,
                "error": f"Internal server error: {str(e)}",
            },
        )


def get_template_prompt(template_id: str) -> str:
    """Generate template-specific prompt based on template ID"""
    templates = {
        "standard_meeting": """Generate comprehensive meeting notes with:
        - Key discussion points and topics covered
        - Important decisions made
        - Action items with assignees (if mentioned)
        - Next steps and deadlines
        - Participants and their contributions""",
        "daily_standup": """Generate a concise daily standup summary with:
        - What each person accomplished since last standup
        - What each person plans to work on today
        - Blockers or impediments mentioned
        - Key updates or announcements
        Focus on brevity and clarity.""",
        "interview": """Generate an interview summary with:
        - Candidate background and qualifications discussed
        - Technical skills and experience evaluated
        - Behavioral questions and responses
        - Key strengths and concerns
        - Interviewer impressions
        - Next steps in the hiring process""",
        "brainstorming": """Generate a brainstorming session summary with:
        - All ideas and suggestions proposed
        - Themes or categories of ideas
        - Promising concepts to explore further
        - Voting or prioritization results (if any)
        - Action items for follow-up
        - Participants' contributions to each idea""",
        "standup": """Generate a standup meeting summary with:
        - Updates from each participant (what they accomplished, what they're working on)
        - Blockers and dependencies that need attention
        - Key decisions made during the standup
        - Action items with owners and deadlines
        - Any announcements or upcoming events mentioned
        Focus on quick, actionable items. Keep the summary concise and scannable.""",
    }

    return templates.get(template_id, templates["standard_meeting"])


async def generate_notes_with_gemini_background(
    meeting_id: str,
    transcript_text: str,
    template_id: str,
    meeting_title: str,
    custom_context: str = "",
    user_email: Optional[str] = None,
):
    """Background task to generate meeting notes using Gemini with support for long transcripts"""
    process_id = None
    try:
        logger.info(
            f"Starting Gemini note generation for meeting: {meeting_id} with template: {template_id}"
        )

        # Create process for tracking
        process_id = await processor.db.create_process(meeting_id)
        await processor.db.update_process(process_id, status="processing", result=None)

        # Get Gemini API key
        api_key = await db.get_api_key("gemini", user_email=user_email)
        if not api_key:
            import os

            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            error_msg = "Gemini API key not configured. Please set GOOGLE_API_KEY or GEMINI_API_KEY environment variable."
            logger.error(error_msg)
            await processor.db.update_process(
                process_id, status="failed", error=error_msg
            )
            return

        import google.generativeai as genai

        genai.configure(api_key=api_key)

        # Use gemini-2.0-flash which has a massive context window (1M tokens)
        model_name = "gemini-2.0-flash"
        model = genai.GenerativeModel(model_name)

        # Get template-specific instructions
        template_instructions = get_template_prompt(template_id)

        # Build context section if provided
        context_section = ""
        if custom_context and custom_context.strip():
            context_section = f"""
User-Provided Context:
---
{custom_context}
---
Use this context to better understand the meeting participants, purpose, and important topics to focus on.
"""

        # For very long transcripts, we'll inform the model about the length and ask for a comprehensive summary
        is_long_meeting = len(transcript_text) > 100000  # ~15k-20k words
        length_guidance = ""
        if is_long_meeting:
            length_guidance = "\nNote: This is a long meeting. Please ensure the summary is comprehensive and covers the entire duration of the transcript without omitting later parts.\n"

        # CHUNKING LOGIC
        # Split transcript into chunks to avoid output token limits/truncation
        chunk_size = 40000
        chunks = [
            transcript_text[i : i + chunk_size]
            for i in range(0, len(transcript_text), chunk_size)
        ]

        full_markdown_notes = ""
        logger.info(
            f"Processing transcript in {len(chunks)} chunks (size: {chunk_size})"
        )

        for i, chunk in enumerate(chunks):
            is_first = i == 0
            part_label = f"Part {i + 1}/{len(chunks)}"

            logger.info(f"Generating notes for {part_label}...")

            # Create comprehensive prompt for note generation
            prompt = f"""You are an expert meeting notes generator. Generate well-structured meeting notes in Markdown format based on the following transcript segment.

This is {part_label} of the meeting.

Template Instructions:
{template_instructions}

{context_section}{length_guidance}
IMPORTANT GUIDELINES:

Generate the notes in Markdown format with the following structure:

**Spelling & Transcription Errors:**
- The transcript is from speech-to-text and WILL contain spelling mistakes, misheard words, and phonetic errors
- Use the context of the discussion to infer correct spellings (e.g., "react native" not "react naitive", "API" not "a p i")
- Technical terms, product names, people's names, and acronyms are commonly misspelled - correct them based on context
- If unsure about a spelling, use the most likely correct version based on the meeting context

**Formatting:**
- Use proper headings (## for main sections, ### for subsections)
- Use bullet points for lists
- **Speaker Attribution:** If the transcript includes speaker labels (e.g., "Speaker 1:", "Alice:"), attribute key points, decisions, and action items to the correct person. 
    - Example: "- **Alice** suggested to delay the release." instead of "- A decision was made to delay."
    - Example: "- [Action] **Bob** to check the logs." instead of "- Check the logs."

- Use bold for important items (like action items, decisions)
- Include participants if mentioned
- Be concise but comprehensive
- NEVER use code blocks (``` or ```) in the output - use plain text or bullet points instead

Meeting Title: {meeting_title} ({part_label})

Transcript Segment:
---
{chunk}
---

Generate comprehensive meeting notes in Markdown format for THIS SEGMENT only. 
{"Include a main title." if is_first else "Do NOT include a main title (start with ## Section)."}
At the END of the notes, add a section:

## 📝 Transcription Corrections ({part_label})
List any significant spelling/word corrections you made from the original transcript. Format as:
- "original word/phrase" → "corrected word/phrase" (reason if not obvious)

Only include corrections that meaningfully affect understanding (skip minor typos). If no significant corrections were needed, write "No significant corrections needed."

Now generate the meeting notes:"""

            try:
                # Generate notes with Gemini - increase max_output_tokens for long transcripts
                response = await model.generate_content_async(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.2,  # Lower temperature for more factual notes
                        max_output_tokens=8192,  # Ensure enough space for detailed notes
                    ),
                )

                if not response or not response.text:
                    error_msg = f"Gemini returned empty response for chunk {i + 1}"
                    logger.error(error_msg)
                    full_markdown_notes += (
                        f"\n\n[Error: Could not generate notes for {part_label}]\n\n"
                    )
                    continue

                full_markdown_notes += response.text.strip() + "\n\n"
            except Exception as e:
                logger.error(f"Error processing chunk {i + 1}: {str(e)}")
                full_markdown_notes += (
                    f"\n\n[Error processing {part_label}: {str(e)}]\n\n"
                )

        markdown_notes = full_markdown_notes.strip()

        # Extract meeting title if generated
        meeting_name = meeting_title
        if "Meeting Title:" in markdown_notes or "# " in markdown_notes:
            lines = markdown_notes.split("\n")
            for line in lines[:5]:  # Check first few lines
                if line.startswith("# ") and not line.startswith("## "):
                    meeting_name = line.replace("# ", "").strip()
                    break

        # Format the summary in the expected structure
        summary_data = {"markdown": markdown_notes, "MeetingName": meeting_name}

        # Update meeting name if different
        if meeting_name and meeting_name != meeting_title:
            await processor.db.update_meeting_name(meeting_id, meeting_name)

        # Save the summary
        await processor.db.update_process(
            process_id, status="completed", result=summary_data
        )
        logger.info(
            f"✅ Successfully generated notes for meeting: {meeting_id} using Gemini {model_name}"
        )

    except Exception as e:
        error_msg = f"Error generating notes with Gemini: {str(e)}"
        logger.error(error_msg, exc_info=True)
        try:
            if process_id:
                await processor.db.update_process(
                    process_id, status="failed", error=error_msg
                )
            else:
                # Create process just to track the failure
                process_id = await processor.db.create_process(meeting_id)
                await processor.db.update_process(
                    process_id, status="failed", error=error_msg
                )
        except Exception as db_e:
            logger.error(f"Failed to update DB status to failed: {db_e}", exc_info=True)


@app.post("/save-transcript")
async def save_transcript(
    request: SaveTranscriptRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Save transcript segments for a meeting and automatically generate notes based on template"""
    try:
        logger.info(
            f"Received save-transcript request for meeting: {request.meeting_title}"
        )
        logger.info(f"Number of transcripts to save: {len(request.transcripts)}")
        logger.info(f"Template ID: {request.template_id}")

        # Log first transcript timestamps for debugging
        if request.transcripts:
            first = request.transcripts[0]
            logger.debug(
                f"First transcript: audio_start_time={first.audio_start_time}, audio_end_time={first.audio_end_time}, duration={first.duration}"
            )

        # Generate a unique meeting ID
        meeting_id = f"meeting-{int(time.time() * 1000)}"

        # Save the meeting with folder path (if provided) and owner
        await db.save_meeting(
            meeting_id,
            request.meeting_title,
            folder_path=request.folder_path,
            owner_id=current_user.email,
        )

        # LINK AUDIO RECORDING: Move audio from session_id folder to meeting_id folder
        if request.session_id:
            try:
                # Import here to avoid circular dependencies if any
                from audio_recorder import AudioRecorder, stop_recorder

                # 1. Stop the active recorder if it's still running
                # (usually stopped via websocket close, but ensure consistency)
                await stop_recorder(request.session_id)

                # 2. Rename the directory to the final meeting_id
                # This makes it findable by the Diarization job and /diarize endpoint
                linked = await AudioRecorder.rename_recorder_folder(
                    request.session_id, meeting_id
                )
                if linked:
                    logger.info(
                        f"✅ Successfully linked recording from session {request.session_id} to meeting {meeting_id}"
                    )
                    # Update meeting in DB to flag that audio exists
                    async with db._get_connection() as conn:
                        await conn.execute(
                            "UPDATE meetings SET audio_recorded = TRUE WHERE id = $1",
                            meeting_id,
                        )
            except Exception as e:
                logger.error(
                    f"⚠️ Failed to link audio recording session {request.session_id}: {e}"
                )

        # Save each transcript segment with NEW timestamp fields for playback sync
        full_transcript_text = ""
        for transcript in request.transcripts:
            await db.save_meeting_transcript(
                meeting_id=meeting_id,
                transcript=transcript.text,
                timestamp=transcript.timestamp,
                summary="",
                action_items="",
                key_points="",
                # NEW: Recording-relative timestamps for audio-transcript synchronization
                audio_start_time=transcript.audio_start_time,
                audio_end_time=transcript.audio_end_time,
                duration=transcript.duration,
            )
            full_transcript_text += transcript.text + "\n"

        # Also save to full_transcripts table for consistency with process-transcript flow
        if full_transcript_text.strip():
            await db.save_transcript(
                meeting_id=meeting_id,
                transcript_text=full_transcript_text,
                model="user-recording",
                model_name="user-recording",
                chunk_size=0,
                overlap=0,
            )

        logger.info("Transcripts saved successfully")

        # Store embeddings for cross-meeting search
        try:
            from vector_store import store_meeting_embeddings

            transcript_dicts = [
                {"text": t.text, "timestamp": t.timestamp} for t in request.transcripts
            ]
            chunks_stored = await store_meeting_embeddings(
                meeting_id=meeting_id,
                meeting_title=request.meeting_title,
                meeting_date=datetime.now().isoformat(),
                transcripts=transcript_dicts,
            )
            logger.info(
                f"✅ Stored {chunks_stored} embedding chunks for cross-meeting search"
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to store embeddings (non-critical): {e}")

        # Automatically trigger note generation using Gemini
        if full_transcript_text.strip():
            try:
                logger.info(
                    f"Auto-generating notes with Gemini using template: {request.template_id}"
                )

                # Use Gemini for note generation (always use Gemini as specified)
                background_tasks.add_task(
                    generate_notes_with_gemini_background,
                    meeting_id,
                    full_transcript_text,
                    request.template_id or "standard_meeting",
                    request.meeting_title,
                    "",  # custom_context
                    current_user.email,
                )
                logger.info(
                    f"Started automatic note generation with Gemini for meeting: {meeting_id}"
                )
            except Exception as e:
                logger.error(
                    f"Error starting automatic note generation: {str(e)}", exc_info=True
                )
                # Don't fail the save if auto-generation fails

        return {
            "status": "success",
            "message": "Transcript saved successfully",
            "meeting_id": meeting_id,
        }
    except Exception as e:
        logger.error(f"Error saving transcript: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-model-config")
async def get_model_config(current_user: User = Depends(get_current_user)):
    """Get the current model configuration"""
    model_config = await db.get_model_config()
    if model_config:
        api_key = await db.get_api_key(
            model_config["provider"], user_email=current_user.email
        )
        if api_key != None:
            model_config["apiKey"] = api_key
    return model_config


@app.post("/save-model-config")
async def save_model_config(
    request: SaveModelConfigRequest, current_user: User = Depends(get_current_user)
):
    """Save the model configuration"""
    await db.save_model_config(request.provider, request.model, request.whisperModel)
    if request.apiKey != None:
        await db.save_api_key(request.apiKey, request.provider)
    return {"status": "success", "message": "Model configuration saved successfully"}


@app.get("/get-transcript-config")
async def get_transcript_config(current_user: User = Depends(get_current_user)):
    """Get the current transcript configuration"""
    transcript_config = await db.get_transcript_config()
    if transcript_config:
        transcript_api_key = await db.get_transcript_api_key(
            transcript_config["provider"], user_email=current_user.email
        )
        if transcript_api_key != None:
            transcript_config["apiKey"] = transcript_api_key
    return transcript_config


@app.post("/save-transcript-config")
async def save_transcript_config(request: SaveTranscriptConfigRequest):
    """Save the transcript configuration"""
    await db.save_transcript_config(request.provider, request.model)
    if request.apiKey != None:
        await db.save_transcript_api_key(request.apiKey, request.provider)
    return {
        "status": "success",
        "message": "Transcript configuration saved successfully",
    }


class GetApiKeyRequest(BaseModel):
    provider: str


@app.post("/get-api-key")
async def get_api_key_api(
    request: GetApiKeyRequest, current_user: User = Depends(get_current_user)
):
    try:
        return await db.get_api_key(request.provider, user_email=current_user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/get-transcript-api-key")
async def get_transcript_api_key_api(
    request: GetApiKeyRequest, current_user: User = Depends(get_current_user)
):
    try:
        return await db.get_transcript_api_key(
            request.provider, user_email=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- User Personal API Keys Endpoints ---


class UserApiKeySaveRequest(BaseModel):
    provider: str
    api_key: str


@app.get("/api/user/keys")
async def get_user_keys(current_user: User = Depends(get_current_user)):
    """Get masked API keys for the current user"""
    try:
        return await db.get_user_api_keys(current_user.email)
    except Exception as e:
        logger.error(f"Error fetching user keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch keys")


@app.post("/api/user/keys")
async def save_user_key(
    request: UserApiKeySaveRequest, current_user: User = Depends(get_current_user)
):
    """Save/Update an encrypted API key for the current user"""
    try:
        await db.save_user_api_key(
            current_user.email, request.provider, request.api_key
        )
        return {"status": "success", "message": f"API key for {request.provider} saved"}
    except Exception as e:
        logger.error(f"Error saving user key: {e}")
        raise HTTPException(status_code=500, detail="Failed to save key")


@app.delete("/api/user/keys/{provider}")
async def delete_user_key(
    provider: str, current_user: User = Depends(get_current_user)
):
    """Delete an API key for the current user"""
    try:
        await db.delete_user_api_key(current_user.email, provider)
        return {"status": "success", "message": f"API key for {provider} deleted"}
    except Exception as e:
        logger.error(f"Error deleting user key: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete key")


class MeetingSummaryUpdate(BaseModel):
    meeting_id: str
    summary: dict


@app.post("/save-meeting-summary")
async def save_meeting_summary(data: MeetingSummaryUpdate):
    """Save a meeting summary"""
    try:
        await db.update_meeting_summary(data.meeting_id, data.summary)
        return {"message": "Meeting summary saved successfully"}
    except ValueError as ve:
        logger.error(f"Value error saving meeting summary: {str(ve)}")
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Error saving meeting summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class SearchRequest(BaseModel):
    query: str


@app.post("/search-transcripts")
async def search_transcripts(request: SearchRequest):
    """Search through meeting transcripts for the given query"""
    try:
        results = await db.search_transcripts(request.query)
        return JSONResponse(content=results)
    except Exception as e:
        logger.error(f"Error searching transcripts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Transcription WebSocket Endpoint (Multi-Provider Architecture)
# ============================================================================

from streaming_transcription import StreamingTranscriptionManager

# Global streaming managers (one per session)
streaming_managers = {}
# Track active connections per session to prevent premature cleanup
active_connections = {}


@app.get("/meetings/{meeting_id}/versions")
async def get_transcript_versions(
    meeting_id: str, current_user: User = Depends(get_current_user)
):
    """Get all transcript versions for a meeting"""
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        versions = await db.get_transcript_versions(meeting_id)
        return {"versions": versions}
    except Exception as e:
        logger.error(f"Error fetching versions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/meetings/{meeting_id}/versions/{version_num}")
async def get_transcript_version_content(
    meeting_id: str, version_num: int, current_user: User = Depends(get_current_user)
):
    """Get content of a specific transcript version"""
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        content = await db.get_transcript_version_content(meeting_id, version_num)
        if not content:
            raise HTTPException(status_code=404, detail="Version not found")
        return {"content": content}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching version content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/streaming-audio")
async def websocket_streaming_audio(
    websocket: WebSocket,
    session_id: Optional[str] = None,
    user_email: Optional[str] = None,
    meeting_id: Optional[str] = None,
):
    """
    Real-time streaming transcription with Groq Whisper Large v3.
    Includes heartbeat and force-flush on disconnect.
    """
    await websocket.accept()

    # Check if resuming session
    is_resume = False
    if session_id and session_id in streaming_managers:
        manager = streaming_managers[session_id]
        is_resume = True
        logger.info(f"[Streaming] 🔄 Resuming session {session_id}")
    else:
        # Create new session
        session_id = str(uuid.uuid4()) if not session_id else session_id
        is_resume = False

    # Audio recorder setup
    audio_recorder = None
    enable_recording = os.getenv("ENABLE_AUDIO_RECORDING", "true").lower() == "true"

    if enable_recording:
        try:
            recorder_key = meeting_id or session_id
            audio_recorder = await get_or_create_recorder(recorder_key)
            logger.info(
                f"[Streaming] 🎙️ Audio recording active using key: {recorder_key}"
            )
        except Exception as e:
            logger.warning(f"[Streaming] Failed to start audio recorder: {e}")

    if not is_resume:
        groq_api_key = (
            await db.get_user_api_key(user_email, "groq") if user_email else None
        )
        if not groq_api_key:
            logger.warning(
                f"[Streaming] No personal Groq API key for user: {user_email}"
            )
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "GROQ_KEY_REQUIRED",
                    "message": "Groq API key required. Please add your Groq API key in Settings → Personal Keys.",
                }
            )
            await websocket.close()
            return

        manager = StreamingTranscriptionManager(groq_api_key)
        streaming_managers[session_id] = manager
        logger.info(f"[Streaming] ✅ Session {session_id} started (HYBRID mode)")

    # Register active connection
    if session_id not in active_connections:
        active_connections[session_id] = 0
    active_connections[session_id] += 1

    # Heartbeat Setup
    last_heartbeat = time.time()
    HEARTBEAT_TIMEOUT = 15.0  # seconds

    async def heartbeat_monitor():
        try:
            while True:
                await asyncio.sleep(5)
                if time.time() - last_heartbeat > HEARTBEAT_TIMEOUT:
                    logger.warning(f"Session {session_id}: Heartbeat timeout, closing")
                    await websocket.close()
                    break
        except Exception:
            pass

    monitor_task = asyncio.create_task(heartbeat_monitor())

    # Send connection confirmation
    await websocket.send_json(
        {
            "type": "connected",
            "session_id": session_id,
            "message": "Groq streaming ready (HYBRID mode)",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )

    # Define callbacks (on_partial, on_final, on_error) - reused from existing code
    async def on_partial(data):
        try:
            await websocket.send_json(
                {
                    "type": "partial",
                    "text": data["text"],
                    "confidence": data["confidence"],
                    "is_stable": data.get("is_stable", False),
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
        except Exception:
            pass

    async def on_final(data):
        try:
            response = {
                "type": "final",
                "text": data["text"],
                "confidence": data["confidence"],
                "reason": data.get("reason", "unknown"),
                "timestamp": datetime.utcnow().isoformat(),
                "audio_start_time": data.get("audio_start_time"),
                "audio_end_time": data.get("audio_end_time"),
                "duration": data.get("duration"),
            }
            if data.get("original_text"):
                response["original_text"] = data["original_text"]
                response["translated"] = data.get("translated", False)
            await websocket.send_json(response)
        except Exception:
            pass

    async def on_error(message: str, code: Optional[str] = None):
        try:
            error_payload = {
                "type": "error",
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
            }
            if code:
                error_payload["code"] = code

            await websocket.send_json(error_payload)
        except Exception:
            pass

    # Audio Queue
    audio_queue = asyncio.Queue()

    async def audio_worker():
        try:
            while True:
                item = await audio_queue.get()
                if item is None:
                    audio_queue.task_done()
                    break

                if isinstance(item, tuple):
                    chunk, ts = item
                else:
                    chunk = item
                    ts = None

                try:
                    await manager.process_audio_chunk(
                        audio_data=chunk,
                        client_timestamp=ts,
                        on_partial=on_partial,
                        on_final=on_final,
                        on_error=on_error,
                    )
                except Exception as e:
                    logger.error(f"[Streaming] Worker transcription error: {e}")

                audio_queue.task_done()
        except Exception as e:
            logger.error(f"[Streaming] Audio worker crashed: {e}")

    worker_task = asyncio.create_task(audio_worker())

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), timeout=HEARTBEAT_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[Streaming] No message received in {HEARTBEAT_TIMEOUT}s"
                )
                break

            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    if data.get("type") == "ping":
                        last_heartbeat = time.time()
                        await websocket.send_json({"type": "pong"})
                        continue
                except:
                    pass

            if "bytes" in message:
                message_bytes = message["bytes"]
                timestamp = None
                audio_chunk = message_bytes

                if len(message_bytes) >= 8:
                    try:
                        timestamp_bytes = message_bytes[:8]
                        (timestamp,) = struct.unpack("<d", timestamp_bytes)
                        audio_chunk = message_bytes[8:]
                    except:
                        audio_chunk = message_bytes

                if audio_recorder:
                    await audio_recorder.add_chunk(audio_chunk)

                await audio_queue.put((audio_chunk, timestamp))

    except WebSocketDisconnect:
        logger.info(f"[Streaming] Session {session_id} disconnected by client")
    except Exception as e:
        logger.error(f"[Streaming] Error in receiver loop {session_id}: {e}")

    finally:
        monitor_task.cancel()

        # Force flush on disconnect
        if session_id in streaming_managers:
            try:
                mgr = streaming_managers[session_id]
                flush_result = await mgr.force_flush()
                if flush_result:
                    # Try to send final segment if socket still open (unlikely but possible)
                    try:
                        await on_final(flush_result)
                    except:
                        pass

                    # Also explicitly save this flush segment to DB if we can
                    # (requires meeting_id context which we have)
                    if meeting_id:
                        try:
                            async with db._get_connection() as conn:
                                await conn.execute(
                                    """
                                    INSERT INTO transcript_segments (
                                        meeting_id, transcript, timestamp, source, alignment_state, audio_start_time
                                    ) VALUES ($1, $2, $3, 'live', 'CONFIDENT', $4)
                                """,
                                    meeting_id,
                                    flush_result["text"],
                                    datetime.utcnow(),
                                    mgr.speech_start_time,
                                )
                        except Exception as db_e:
                            logger.error(f"Failed to save flush segment to DB: {db_e}")

            except Exception as e:
                logger.error(f"Force flush failed: {e}")

        # Cleanup queues and workers
        await audio_queue.put(None)
        try:
            await asyncio.wait_for(worker_task, timeout=5.0)
        except:
            pass

        # Recorder cleanup
        if audio_recorder:
            try:
                recorder_key = meeting_id or session_id
                await stop_recorder(recorder_key)
            except:
                pass

        # Connection tracking cleanup
        if session_id in active_connections:
            active_connections[session_id] -= 1
            if active_connections[session_id] <= 0:
                if session_id in streaming_managers:
                    manager.cleanup()
                    del streaming_managers[session_id]
                del active_connections[session_id]


@app.get("/list-meetings")
async def list_meetings():
    """List all available meetings with basic metadata."""
    try:
        meetings = await db.get_all_meetings()
        return [
            {
                "id": m["id"],
                "title": m["title"],
                "date": m["created_at"],  # get_all_meetings returns 'created_at'
            }
            for m in meetings
        ]
    except Exception as e:
        logger.error(f"Error listing meetings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/reindex-all")
async def reindex_all():
    """Admin endpoint to re-index all past meetings into ChromaDB."""
    debug_logs = []
    try:
        try:
            import sentence_transformers

            debug_logs.append("sentence_transformers imported successfully")
        except ImportError:
            logger.error("sentence-transformers not installed")
            raise HTTPException(
                status_code=500,
                detail="sentence-transformers library is missing on the server",
            )

        from vector_store import store_meeting_embeddings

        # 1. Fetch all meetings
        meetings = await db.get_all_meetings()
        debug_logs.append(f"Fetched {len(meetings)} meetings from DB")
        logger.info(f"Re-indexing {len(meetings)} meetings...")

        count = 0
        successful = 0
        failed = 0
        skipped = 0
        errors = []

        for m in meetings:
            meeting_id = m["id"]

            try:
                # 2. Get full details including transcripts
                meeting_data = await db.get_meeting(meeting_id)
                transcripts = []

                if meeting_data and meeting_data.get("transcripts"):
                    transcripts = meeting_data.get("transcripts")
                    debug_logs.append(
                        f"Meeting {meeting_id}: Found {len(transcripts)} transcripts in structure"
                    )
                else:
                    # Fallback to full_transcripts table
                    full_text = await db.get_full_transcript_text(meeting_id)
                    if full_text:
                        logger.info(f"Using fallback full transcript for {meeting_id}")
                        transcripts = [
                            {
                                "text": full_text,
                                "timestamp": meeting_data.get("created_at")
                                if meeting_data
                                else "",
                                "id": meeting_id,
                            }
                        ]
                        debug_logs.append(
                            f"Meeting {meeting_id}: Found full transcript text"
                        )
                    else:
                        debug_logs.append(f"Meeting {meeting_id}: No transcripts found")

                if not transcripts:
                    logger.info(f"Skipping {meeting_id}: no transcripts")
                    skipped += 1
                    continue

                # 3. Store in vector DB (sequential processing to avoid ChromaDB race conditions)
                num_chunks = await store_meeting_embeddings(
                    meeting_id=meeting_id,
                    meeting_title=meeting_data.get("title", "Untitled")
                    if meeting_data
                    else m["title"],
                    meeting_date=meeting_data.get("created_at", "")
                    if meeting_data
                    else m.get("created_at", ""),
                    transcripts=transcripts,
                )

                debug_logs.append(f"Meeting {meeting_id}: Stored {num_chunks} chunks")

                if num_chunks > 0:
                    successful += 1
                    logger.info(f"✅ Indexed meeting {meeting_id}: {num_chunks} chunks")
                else:
                    logger.warning(
                        f"⚠️ Meeting {meeting_id} indexed but produced 0 chunks"
                    )
                    # If 0 chunks but no error, we count it as processed but maybe not "successful" in terms of vectors?
                    # Let's count it as successful but 0 chunks.

                count += 1

                # Small delay to ensure ChromaDB processes fully before next meeting
                await asyncio.sleep(0.05)

            except Exception as e:
                failed += 1
                error_msg = f"Failed to index {meeting_id}: {str(e)}"
                logger.error(f"❌ {error_msg}")
                errors.append(error_msg)
                debug_logs.append(f"ERROR {meeting_id}: {str(e)}")
                continue  # Continue with next meeting even if one fails

        return {
            "status": "success",
            "indexed_count": count,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "total_meetings": len(meetings),
            "errors": errors,
            "debug_logs": debug_logs,
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Re-indexing failed: {e}")
        return {"status": "error", "error": str(e), "debug_logs": debug_logs}


# ============================================


@app.post("/upload-meeting-recording")
async def upload_meeting_recording(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process an audio/video file as a new meeting.
    """
    meeting_id = str(uuid.uuid4())
    meeting_title = title or file.filename or "Untitled Import"

    # 1. Create meeting entry in DB
    # We use the global db instance
    await db.save_meeting(
        meeting_id=meeting_id,
        title=meeting_title,
        owner_id=current_user.email if current_user else "default",
        workspace_id="default",
    )

    # 2. Save file temporarily
    # Need to handle filename carefully
    original_filename = file.filename or "uploaded_file"
    file_ext = os.path.splitext(original_filename)[1]
    if not file_ext:
        file_ext = ".bin"  # Fallback

    upload_dir = Path("./data/uploads") / meeting_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"original{file_ext}"

    try:
        async with aiofiles.open(file_path, "wb") as out_file:
            while content := await file.read(1024 * 1024):  # 1MB chunks
                await out_file.write(content)
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # 3. Trigger processing
    processor = get_file_processor(db)
    background_tasks.add_task(
        processor.process_file, meeting_id, file_path, meeting_title
    )

    return {
        "meeting_id": meeting_id,
        "status": "processing",
        "message": "File uploaded and processing started",
    }


# Diarization Endpoints
# ============================================


@app.post("/meetings/{meeting_id}/diarize")
async def diarize_meeting(
    meeting_id: str,
    request: DiarizeRequest = None,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
):
    """
    Trigger speaker diarization for a meeting.

    This endpoint:
    1. Verifies the meeting exists and has recorded audio
    2. Starts a background job to process the audio
    3. Returns immediately with status 'processing'

    Diarization results can be polled via GET /meetings/{id}/diarization-status
    """
    if not await rbac.can(current_user, "ai_interact", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        # Check if meeting exists
        meeting = await db.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        # Check if audio was recorded
        from pathlib import Path

        recording_path = Path(f"./data/recordings/{meeting_id}")

        if not recording_path.exists():
            raise HTTPException(
                status_code=400,
                detail="No audio recording directory found.",
            )

        has_chunks = bool(list(recording_path.glob("chunk_*.pcm")))
        has_merged = (recording_path / "merged_recording.pcm").exists() or (
            recording_path / "merged_recording.wav"
        ).exists()

        if not has_chunks and not has_merged:
            raise HTTPException(
                status_code=400,
                detail="No audio recording found for this meeting. Enable recording first.",
            )

        provider = request.provider if request else "deepgram"

        # Create diarization job record in database
        try:
            async with db._get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO diarization_jobs (meeting_id, status, provider, started_at)
                    VALUES ($1, 'processing', $2, $3)
                    ON CONFLICT (meeting_id) 
                    DO UPDATE SET status = 'processing', provider = $2, started_at = $3, error_message = NULL
                """,
                    meeting_id,
                    provider,
                    datetime.utcnow(),
                )

                await conn.execute(
                    """
                    UPDATE meetings SET diarization_status = 'processing' WHERE id = $1
                """,
                    meeting_id,
                )
        except Exception as e:
            logger.warning(f"DB update warning (continuing): {e}")

        # Start background diarization job
        background_tasks.add_task(
            run_diarization_job, meeting_id, provider, current_user.email
        )

        return JSONResponse(
            {
                "status": "processing",
                "message": f"Diarization started with {provider}",
                "meeting_id": meeting_id,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start diarization for {meeting_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def run_diarization_job(meeting_id: str, provider: str, user_email: str):
    """
    Background job that runs speaker diarization using the Gold Standard Hybrid Strategy.

    Processing Steps:
    1. Merge all audio chunks into a single WAV.
    2. Run professional Whisper transcription (Groq) for 100% word accuracy.
    3. Run Deepgram Diarization purely for speaker identification.
    4. Align Whisper words with Deepgram speaker labels.
    5. REPLACE the database segments with this high-fidelity version.
    """
    try:
        logger.info(
            f"🎯 Starting Gold Standard Diarization job for meeting {meeting_id}"
        )

        diarization_service = get_diarization_service()
        storage_path = os.getenv("RECORDINGS_STORAGE_PATH", "./data/recordings")

        # 1. Get Audio Data (Handle both Live Chunks and Imported Files)
        recording_dir = Path(storage_path) / meeting_id
        audio_data = None

        # Check for pre-existing merged file (Imported)
        merged_pcm = recording_dir / "merged_recording.pcm"
        merged_wav = recording_dir / "merged_recording.wav"

        if merged_pcm.exists():
            logger.info(f"📂 Found existing merged PCM file for {meeting_id}")
            async with aiofiles.open(merged_pcm, "rb") as f:
                audio_data = await f.read()
        elif merged_wav.exists():
            logger.info(f"📂 Found existing merged WAV file for {meeting_id}")
            async with aiofiles.open(merged_wav, "rb") as f:
                wav_data = await f.read()
                # Skip header for PCM if needed, but DiarizationService handles WAV usually.
                # However, transcribe_with_whisper expects raw PCM usually?
                # Actually transcribe_with_whisper sends to Groq which accepts WAV or PCM?
                # Let's check Groq client. It likely takes raw bytes.
                # But audio_recorder.merge_chunks returns raw PCM bytes.
                # So if we have WAV, we might need to strip header or just pass it if Groq is smart.
                # Safest: Use merged PCM if available. If WAV, maybe read it as bytes.
                audio_data = wav_data
        else:
            # Fallback to merging chunks (Live Recording)
            logger.info(f"🧩 Merging live audio chunks for {meeting_id}")
            audio_data = await AudioRecorder.merge_chunks(meeting_id, storage_path)

        if not audio_data:
            raise ValueError(f"No audio data found for meeting {meeting_id}")

        # 2. Run high-fidelity Whisper transcription (The Words)
        whisper_segments = await diarization_service.transcribe_with_whisper(audio_data)
        if not whisper_segments:
            logger.warning(
                "Whisper transcription returned no segments. Falling back to native provider text."
            )

        # 3. Run Diarization (The Speakers)
        result = await diarization_service.diarize_meeting(
            meeting_id=meeting_id, storage_path=storage_path, provider=provider
        )

        if result.status == "completed":
            logger.info(
                f"✅ Diarization success, aligning with {len(whisper_segments)} high-fidelity segments"
            )

            # 4. ALIGN: Attach speakers to Whisper's high-quality text using 3-tier alignment
            # If whisper failed, diarization_service.align_with_transcripts handles it via fallback
            (
                final_segments,
                alignment_metrics,
            ) = await diarization_service.align_with_transcripts(
                meeting_id,
                result,
                whisper_segments
                if whisper_segments
                else [
                    {"start": s.start_time, "end": s.end_time, "text": s.text}
                    for s in result.segments
                ],
            )

            logger.info(
                f"📊 Alignment metrics: {alignment_metrics.get('confident_count', 0)} confident, "
                f"{alignment_metrics.get('uncertain_count', 0)} uncertain, "
                f"{alignment_metrics.get('overlap_count', 0)} overlap"
            )

            # 5. RE-INSERT into Database (Transactional)
            async with db._get_connection() as conn:
                async with conn.transaction():
                    # --- VERSIONING STRATEGY ---
                    # 1. Check if we should archive the current "Live" transcripts before overwriting.
                    # If this is the FIRST diarization run, we should probably save the raw live transcript as v1.

                    # Fetch current segments to see if we have data to archive
                    current_rows = await conn.fetch(
                        "SELECT * FROM transcript_segments WHERE meeting_id = $1 ORDER BY audio_start_time",
                        meeting_id,
                    )

                    if current_rows:
                        # Check if we already have versions
                        version_count = await conn.fetchval(
                            "SELECT COUNT(*) FROM transcript_versions WHERE meeting_id = $1",
                            meeting_id,
                        )

                        # If no versions exist, archive the current "Live/Raw" state as Version 1
                        # OR if the user explicitly requested a snapshot (we assume implicit here for safety)
                        if version_count == 0:
                            logger.info(
                                f"📦 Archiving original transcript as Version 1 for {meeting_id}"
                            )

                            # Convert rows to list of dicts
                            current_content = [dict(row) for row in current_rows]

                            # Calculate metrics for the old version
                            confidence_metrics = db._calculate_confidence_metrics(
                                current_content
                            )

                            await conn.execute(
                                """
                                INSERT INTO transcript_versions (
                                    meeting_id, version_num, source, content_json,
                                    is_authoritative, created_by, confidence_metrics
                                ) VALUES ($1, 1, 'original_capture', $2, FALSE, 'system', $3)
                                """,
                                meeting_id,
                                json.dumps(current_content, default=str),
                                json.dumps(confidence_metrics),
                            )

                    # ---------------------------

                    # Clear old transcripts (Replcae Live View with Diarized View)
                    await conn.execute(
                        "DELETE FROM transcript_segments WHERE meeting_id = $1",
                        meeting_id,
                    )

                    # Insert Gold Standard transcripts with alignment metadata
                    for i, t in enumerate(final_segments):
                        start = t.get("start", t.get("audio_start_time", 0))
                        end = t.get("end", t.get("audio_end_time", start + 2))
                        text = t.get("text", t.get("transcript", ""))
                        speaker = t.get("speaker", "Speaker 0")

                        # Alignment metadata from new AlignmentEngine
                        alignment_state = t.get("alignment_state", "CONFIDENT")
                        alignment_method = t.get("alignment_method", "time_overlap")
                        speaker_confidence = t.get("speaker_confidence", 1.0)

                        # Format timestamp (MM:SS)
                        ts = f"({int(start // 60):02d}:{int(start % 60):02d})"

                        await conn.execute(
                            """
                            INSERT INTO transcript_segments (
                                meeting_id, transcript, timestamp, speaker,
                                audio_start_time, audio_end_time, duration,
                                audio_start_time_raw, audio_end_time_raw, formatted_time,
                                alignment_state, alignment_method, speaker_confidence,
                                source
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                        """,
                            meeting_id,
                            text,
                            ts,
                            speaker,
                            start,
                            end,
                            (end - start),
                            start,
                            end,
                            ts,  # Raw timestamps + formatted
                            alignment_state,
                            alignment_method,
                            speaker_confidence,
                            "diarized",  # Source is 'diarized' for post-processed transcripts
                        )

                    # Update meeting_speakers mapping
                    unique_speakers = set(s.speaker for s in result.segments)
                    for speaker_label in unique_speakers:
                        await conn.execute(
                            """
                            INSERT INTO meeting_speakers (meeting_id, diarization_label, display_name)
                            VALUES ($1, $2, $2)
                            ON CONFLICT (meeting_id, diarization_label) DO NOTHING
                        """,
                            meeting_id,
                            speaker_label,
                        )

                    # --- SAVE DIARIZED VERSION ---
                    # Save the NEW diarized transcript as the next Version
                    next_version = await conn.fetchval(
                        "SELECT COALESCE(MAX(version_num), 0) + 1 FROM transcript_versions WHERE meeting_id = $1",
                        meeting_id,
                    )

                    logger.info(f"💾 Saving Diarized result as Version {next_version}")

                    # Calculate metrics
                    new_metrics = db._calculate_confidence_metrics(final_segments)

                    await conn.execute(
                        """
                        INSERT INTO transcript_versions (
                            meeting_id, version_num, source, content_json,
                            is_authoritative, created_by, alignment_config, confidence_metrics
                        ) VALUES ($1, $2, 'diarization', $3, TRUE, $4, $5, $6)
                        """,
                        meeting_id,
                        next_version,
                        json.dumps(final_segments, default=str),
                        user_email,
                        json.dumps(alignment_metrics),
                        json.dumps(new_metrics),
                    )

                    # Ensure previous versions are not authoritative
                    await conn.execute(
                        """
                        UPDATE transcript_versions 
                        SET is_authoritative = FALSE 
                        WHERE meeting_id = $1 AND version_num != $2
                        """,
                        meeting_id,
                        next_version,
                    )
                    # -----------------------------

                    # Update full_transcripts for AI Note generation
                    formatted_text = (
                        diarization_service.format_transcript_with_speakers(
                            final_segments
                        )
                    )

        diarization_service = get_diarization_service()
        storage_path = os.getenv("RECORDINGS_STORAGE_PATH", "./data/recordings")

        # 1. Merge audio chunks
        audio_data = await AudioRecorder.merge_chunks(meeting_id, storage_path)
        if not audio_data:
            raise ValueError(f"No audio data found for meeting {meeting_id}")

        # 2. Run high-fidelity Whisper transcription (The Words)
        whisper_segments = await diarization_service.transcribe_with_whisper(audio_data)
        if not whisper_segments:
            logger.warning(
                "Whisper transcription returned no segments. Falling back to native provider text."
            )

        # 3. Run Diarization (The Speakers)
        result = await diarization_service.diarize_meeting(
            meeting_id=meeting_id, storage_path=storage_path, provider=provider
        )

        if result.status == "completed":
            logger.info(
                f"✅ Diarization success, aligning with {len(whisper_segments)} high-fidelity segments"
            )

            # 4. ALIGN: Attach speakers to Whisper's high-quality text using 3-tier alignment
            # If whisper failed, diarization_service.align_with_transcripts handles it via fallback
            (
                final_segments,
                alignment_metrics,
            ) = await diarization_service.align_with_transcripts(
                meeting_id,
                result,
                whisper_segments
                if whisper_segments
                else [
                    {"start": s.start_time, "end": s.end_time, "text": s.text}
                    for s in result.segments
                ],
            )

            logger.info(
                f"📊 Alignment metrics: {alignment_metrics.get('confident_count', 0)} confident, "
                f"{alignment_metrics.get('uncertain_count', 0)} uncertain, "
                f"{alignment_metrics.get('overlap_count', 0)} overlap"
            )

            # 5. RE-INSERT into Database (Transactional)
            async with db._get_connection() as conn:
                async with conn.transaction():
                    # Clear old live transcripts
                    await conn.execute(
                        "DELETE FROM transcript_segments WHERE meeting_id = $1",
                        meeting_id,
                    )

                    # Insert Gold Standard transcripts with alignment metadata
                    for i, t in enumerate(final_segments):
                        start = t.get("start", t.get("audio_start_time", 0))
                        end = t.get("end", t.get("audio_end_time", start + 2))
                        text = t.get("text", t.get("transcript", ""))
                        speaker = t.get("speaker", "Speaker 0")

                        # Alignment metadata from new AlignmentEngine
                        alignment_state = t.get("alignment_state", "CONFIDENT")
                        alignment_method = t.get("alignment_method", "time_overlap")
                        speaker_confidence = t.get("speaker_confidence", 1.0)

                        # Format timestamp (MM:SS)
                        ts = f"({int(start // 60):02d}:{int(start % 60):02d})"

                        await conn.execute(
                            """
                            INSERT INTO transcript_segments (
                                meeting_id, transcript, timestamp, speaker,
                                audio_start_time, audio_end_time, duration,
                                audio_start_time_raw, audio_end_time_raw, formatted_time,
                                alignment_state, alignment_method, speaker_confidence,
                                source
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                        """,
                            meeting_id,
                            text,
                            ts,
                            speaker,
                            start,
                            end,
                            (end - start),
                            start,
                            end,
                            ts,  # Raw timestamps + formatted
                            alignment_state,
                            alignment_method,
                            speaker_confidence,
                            "diarized",  # Source is 'diarized' for post-processed transcripts
                        )

                    # Update meeting_speakers mapping
                    unique_speakers = set(s.speaker for s in result.segments)
                    for speaker_label in unique_speakers:
                        await conn.execute(
                            """
                            INSERT INTO meeting_speakers (meeting_id, diarization_label, display_name)
                            VALUES ($1, $2, $2)
                            ON CONFLICT (meeting_id, diarization_label) DO NOTHING
                        """,
                            meeting_id,
                            speaker_label,
                        )

                    # Update full_transcripts for AI Note generation
                    formatted_text = (
                        diarization_service.format_transcript_with_speakers(
                            final_segments
                        )
                    )

                    await conn.execute(
                        """
                        INSERT INTO full_transcripts (meeting_id, transcript_text, model, model_name, created_at)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (meeting_id) DO UPDATE SET
                            transcript_text = EXCLUDED.transcript_text,
                            model = EXCLUDED.model,
                            model_name = EXCLUDED.model_name
                    """,
                        meeting_id,
                        formatted_text,
                        f"gold-whisper-{provider}",
                        "whisper-v3-large",
                        datetime.utcnow(),
                    )

            # 6. Save Transcript Version (Non-Destructive)
            # Save the diarized transcript as a new version outside the transaction
            version_num = await db.save_transcript_version(
                meeting_id=meeting_id,
                source="diarized",
                content=final_segments,
                is_authoritative=True,  # Make this the authoritative version
                alignment_config={
                    "provider": provider,
                    "alignment_engine": "3-tier",
                    "confidence_threshold": 0.6,
                    "overlap_threshold": 0.5,
                },
                created_by="system",
            )

            logger.info(
                f"💾 Saved transcript version v{version_num} (diarized, authoritative)"
            )

            # 7. Update Job Status
            async with db._get_connection() as conn:
                segments_json = [
                    {
                        "speaker": s.speaker,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "text": s.text,
                    }
                    for s in result.segments
                ]

                await conn.execute(
                    """
                    UPDATE diarization_jobs SET 
                        status = 'completed', completed_at = $1, speaker_count = $2,
                        segment_count = $3, processing_time_seconds = $4, result_json = $5, updated_at = $1
                    WHERE meeting_id = $6
                """,
                    datetime.utcnow(),
                    result.speaker_count,
                    len(result.segments),
                    result.processing_time_seconds,
                    json.dumps(segments_json),
                    meeting_id,
                )

                await conn.execute(
                    """
                    UPDATE meetings SET 
                        diarization_status = 'completed', diarization_provider = $1, diarization_completed_at = $2
                    WHERE id = $3
                """,
                    provider,
                    datetime.utcnow(),
                    meeting_id,
                )

            logger.info(f"✅ Gold Standard recovery complete for {meeting_id}")

        else:
            # Mark as failed in DB
            async with db._get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE diarization_jobs SET 
                        status = 'failed',
                        error_message = $1,
                        updated_at = $2
                    WHERE meeting_id = $3
                """,
                    result.error,
                    datetime.utcnow(),
                    meeting_id,
                )

                await conn.execute(
                    """
                    UPDATE meetings SET diarization_status = 'failed' WHERE id = $1
                """,
                    meeting_id,
                )

            logger.error(f"❌ Diarization failed for {meeting_id}: {result.error}")
            raise ValueError(f"Diarization provider failed: {result.error}")

    except Exception as e:
        logger.error(f"Diarization job error for {meeting_id}: {e}")
        try:
            async with db._get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE diarization_jobs SET 
                        status = 'failed',
                        error_message = $1,
                        updated_at = $2
                    WHERE meeting_id = $3
                """,
                    str(e),
                    datetime.utcnow(),
                    meeting_id,
                )

                await conn.execute(
                    """
                    UPDATE meetings SET diarization_status = 'failed' WHERE id = $1
                """,
                    meeting_id,
                )
        except:
            pass


@app.get(
    "/meetings/{meeting_id}/diarization-status",
    response_model=DiarizationStatusResponse,
)
async def get_diarization_status(
    meeting_id: str, current_user: User = Depends(get_current_user)
):
    """
    Get the diarization status for a meeting.

    Returns:
        - 'pending': No diarization has been attempted
        - 'processing': Diarization is in progress
        - 'completed': Diarization finished successfully
        - 'failed': Diarization failed (check error field)
        - 'not_recorded': No audio was recorded for this meeting
    """
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        # Check if audio exists
        from pathlib import Path

        recording_path = Path(f"./data/recordings/{meeting_id}")

        # Check for chunks or merged files
        has_chunks = bool(list(recording_path.glob("chunk_*.pcm")))
        has_merged = (recording_path / "merged_recording.pcm").exists() or (
            recording_path / "merged_recording.wav"
        ).exists()
        has_audio = recording_path.exists() and (has_chunks or has_merged)

        if not has_audio:
            return DiarizationStatusResponse(
                meeting_id=meeting_id, status="not_recorded"
            )

        # Check database for job status
        async with db._get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT status, speaker_count, provider, error_message, completed_at
                FROM diarization_jobs WHERE meeting_id = $1
            """,
                meeting_id,
            )

        if row:
            return DiarizationStatusResponse(
                meeting_id=meeting_id,
                status=row["status"],
                speaker_count=row["speaker_count"],
                provider=row["provider"],
                error=row["error_message"],
                completed_at=row["completed_at"].isoformat()
                if row["completed_at"]
                else None,
            )

        return DiarizationStatusResponse(meeting_id=meeting_id, status="pending")

    except Exception as e:
        logger.error(f"Failed to get diarization status for {meeting_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/meetings/{meeting_id}/speakers", response_model=SpeakerMappingResponse)
async def get_meeting_speakers(
    meeting_id: str, current_user: User = Depends(get_current_user)
):
    """
    Get speaker label mappings for a meeting.

    Returns list of speakers with their labels and display names.
    """
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        async with db._get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT diarization_label, display_name, color
                FROM meeting_speakers 
                WHERE meeting_id = $1
                ORDER BY diarization_label
            """,
                meeting_id,
            )

        speakers = [
            {
                "label": row["diarization_label"],
                "display_name": row["display_name"] or row["diarization_label"],
                "color": row["color"],
            }
            for row in rows
        ]

        return SpeakerMappingResponse(meeting_id=meeting_id, speakers=speakers)

    except Exception as e:
        logger.error(f"Failed to get speakers for {meeting_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/meetings/{meeting_id}/speakers/{speaker_label}/rename")
async def rename_speaker(
    meeting_id: str,
    speaker_label: str,
    request: RenameSpeakerRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Rename a speaker label to a human-readable name.

    Example: Rename "Speaker 0" to "Alice (Team Lead)"
    """
    if not await rbac.can(current_user, "edit", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        async with db._get_connection() as conn:
            # Update the display name
            result = await conn.execute(
                """
                UPDATE meeting_speakers 
                SET display_name = $1, updated_at = $2
                WHERE meeting_id = $3 AND diarization_label = $4
            """,
                request.display_name,
                datetime.utcnow(),
                meeting_id,
                speaker_label,
            )

            # If no row was updated, the speaker doesn't exist
            if result == "UPDATE 0":
                raise HTTPException(
                    status_code=404, detail=f"Speaker '{speaker_label}' not found"
                )

        logger.info(
            f"Renamed speaker '{speaker_label}' to '{request.display_name}' in meeting {meeting_id}"
        )

        return JSONResponse(
            {
                "status": "success",
                "message": f"Speaker renamed to '{request.display_name}'",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rename speaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/meetings/{meeting_id}/audio-status")
async def get_audio_recording_status(
    meeting_id: str, current_user: User = Depends(get_current_user)
):
    """
    Check if audio has been recorded for a meeting.

    Returns recording metadata if available.
    """
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        from pathlib import Path
        import json as json_lib

        recording_path = Path(f"./data/recordings/{meeting_id}")

        if not recording_path.exists():
            return JSONResponse(
                {"meeting_id": meeting_id, "has_audio": False, "status": "not_recorded"}
            )

        # Get chunk files
        chunks = list(recording_path.glob("chunk_*.pcm"))

        if not chunks:
            return JSONResponse(
                {"meeting_id": meeting_id, "has_audio": False, "status": "not_recorded"}
            )

        # Try to load metadata
        metadata_path = recording_path / "metadata.json"
        metadata = {}
        if metadata_path.exists():
            with open(metadata_path, "r") as f:
                metadata = json_lib.load(f)

        # Calculate total duration
        total_bytes = sum(chunk.stat().st_size for chunk in chunks)
        duration_seconds = total_bytes / (16000 * 2)  # 16kHz, 16-bit

        return JSONResponse(
            {
                "meeting_id": meeting_id,
                "has_audio": True,
                "status": "recorded",
                "chunk_count": len(chunks),
                "duration_seconds": duration_seconds,
                "storage_path": str(recording_path),
                "metadata": metadata,
            }
        )

    except Exception as e:
        logger.error(f"Failed to get audio status for {meeting_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on API shutdown"""
    logger.info("API shutting down, cleaning up resources")
    try:
        processor.cleanup()

        # Cleanup all streaming managers
        for session_id, manager in streaming_managers.items():
            manager.cleanup()
        streaming_managers.clear()

        # Cleanup all audio recorders
        for meeting_id, recorder in list(active_recorders.items()):
            try:
                await recorder.stop()
            except:
                pass
        active_recorders.clear()

        logger.info("Successfully cleaned up resources")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}", exc_info=True)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    uvicorn.run("main:app", host="0.0.0.0", port=5167, reload=True)
