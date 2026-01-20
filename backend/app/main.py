from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
from typing import Optional, List, Dict
import logging
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
from datetime import datetime
from fastapi import Depends, status
from auth import get_current_user, User
from rbac import RBAC

# Configure logger with line numbers and function names
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create console handler with formatting
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# Create formatter with line numbers and function names
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)

# Add handler to logger if not already added
if not logger.handlers:
    logger.addHandler(console_handler)

app = FastAPI(
    title="Meeting Summarizer API",
    description="API for processing and summarizing meeting transcripts",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3118",
        "http://localhost:3000",
        "https://pnyxx.vercel.app",
        "https://meet.digest.lat"
    ],
    allow_credentials=True,
    allow_methods=["*"],     # Allow all methods
    allow_headers=["*"],     # Allow all headers
    max_age=3600,            # Cache preflight requests for 1 hour
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
    folder_path: Optional[str] = None  # NEW: Path to meeting folder (for new folder structure)
    template_id: Optional[str] = "standard_meeting"  # Template for note generation

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
    history: Optional[List[Dict[str, str]]] = None   # Conversation history

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


class SummaryProcessor:
    """Handles the processing of summaries in a thread-safe way"""
    def __init__(self):
        try:
            self.db = DatabaseManager()

            logger.info("Initializing SummaryProcessor components")
            self.transcript_processor = TranscriptProcessor()
            logger.info("SummaryProcessor initialized successfully (core components)")
        except Exception as e:
            logger.error(f"Failed to initialize SummaryProcessor: {str(e)}", exc_info=True)
            raise

    async def process_transcript(self, text: str, model: str, model_name: str, chunk_size: int = 5000, overlap: int = 1000, custom_prompt: str = "Generate a summary of the meeting transcript.") -> tuple:
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

            logger.info(f"Processing transcript of length {len(text)} with chunk_size={chunk_size}, overlap={overlap}")
            num_chunks, all_json_data = await self.transcript_processor.process_transcript(
                text=text,
                model=model,
                model_name=model_name,
                chunk_size=chunk_size,
                overlap=overlap,
                custom_prompt=custom_prompt
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
            if hasattr(self, 'transcript_processor'):
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
        visible_meetings = [
            m for m in meetings 
            if m["id"] in accessible_ids
        ]
        
        return [{"id": meeting["id"], "title": meeting["title"]} for meeting in visible_meetings]
    except Exception as e:
        logger.error(f"Error getting meetings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get-meeting/{meeting_id}", response_model=MeetingDetailsResponse)
async def get_meeting(meeting_id: str, current_user: User = Depends(get_current_user)):
    """Get a specific meeting by ID with all its details"""
    # Permission Check
    if not await rbac.can(current_user, 'view', meeting_id):
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
async def save_meeting_title(data: MeetingTitleUpdate, current_user: User = Depends(get_current_user)):
    """Save a meeting title"""
    if not await rbac.can(current_user, 'edit', data.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to edit this meeting")

    try:
        await db.update_meeting_title(data.meeting_id, data.title)
        return {"message": "Meeting title saved successfully"}
    except Exception as e:
        logger.error(f"Error saving meeting title: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete-meeting")
async def delete_meeting(data: DeleteMeetingRequest, current_user: User = Depends(get_current_user)):
    """Delete a meeting and all its associated data"""
    # Note: Only OWNER (and maybe workspace admin) can delete.
    # Security logic handles this check.
    if not await rbac.can(current_user, 'delete', data.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to delete this meeting")

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
async def save_summary(data: SaveSummaryRequest, current_user: User = Depends(get_current_user)):
    """Save or update meeting summary/notes"""
    if not await rbac.can(current_user, 'edit', data.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to edit summary")

    try:
        logger.info(f"Saving summary for meeting {data.meeting_id}")
        
        # Update the summary_processes table with the new content
        await processor.db.update_process(
            meeting_id=data.meeting_id,
            status="completed",
            result=data.summary
        )
        
        logger.info(f"Successfully saved summary for meeting {data.meeting_id}")
        return {"message": "Summary saved successfully"}
    except Exception as e:
        logger.error(f"Error saving summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def process_transcript_background(process_id: str, transcript: TranscriptRequest, custom_prompt: str, user_email: Optional[str] = None):
    """Background task to process transcript"""
    try:
        logger.info(f"Starting background processing for process_id: {process_id}")
        
        # Early validation for common issues
        if not transcript.text or not transcript.text.strip():
            raise ValueError("Empty transcript text provided")
        
        if transcript.model in ["claude", "groq", "openai", "gemini"]:
            # Check if API key is available for cloud providers
            api_key = await processor.db.get_api_key(transcript.model, user_email=user_email)
            if not api_key:
                # Check for env var fallbacks
                import os
                if transcript.model == "gemini" and (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
                     pass
                else:
                    provider_names = {"claude": "Anthropic", "groq": "Groq", "openai": "OpenAI", "gemini": "Gemini"}
                    raise ValueError(f"{provider_names.get(transcript.model, transcript.model)} API key not configured. Please set your API key in the model settings.")

        # Use template-specific prompt if templateId is provided
        template_prompt = custom_prompt
        template_id = getattr(transcript, 'templateId', None) or getattr(transcript, 'template_id', None)
        if template_id:
            template_prompt = get_template_prompt(template_id)
        
        _, all_json_data = await processor.process_transcript(
            text=transcript.text,
            model=transcript.model,
            model_name=transcript.model_name,
            chunk_size=transcript.chunk_size,
            overlap=transcript.overlap,
            custom_prompt=template_prompt,
            user_email=user_email
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
            "MeetingNotes": {
                "meeting_name": "",
                "sections": []
            }
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
                            final_summary[key]["sections"].extend(json_dict[key]["sections"])
                        if json_dict[key].get("meeting_name"):
                            final_summary[key]["meeting_name"] = json_dict[key]["meeting_name"]
                    elif key != "MeetingName" and key in json_dict and isinstance(json_dict[key], dict) and "blocks" in json_dict[key]:
                        if isinstance(json_dict[key]["blocks"], list):
                            final_summary[key]["blocks"].extend(json_dict[key]["blocks"])
                            # Also add as a new section in MeetingNotes if not already present
                            section_exists = False
                            for section in final_summary["MeetingNotes"]["sections"]:
                                if section["title"] == json_dict[key]["title"]:
                                    section["blocks"].extend(json_dict[key]["blocks"])
                                    section_exists = True
                                    break
                            
                            if not section_exists:
                                final_summary["MeetingNotes"]["sections"].append({
                                    "title": json_dict[key]["title"],
                                    "blocks": json_dict[key]["blocks"].copy() if json_dict[key]["blocks"] else []
                                })
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON chunk for {process_id}: {e}. Chunk: {json_str[:100]}...")
            except Exception as e:
                logger.error(f"Error processing chunk data for {process_id}: {e}. Chunk: {json_str[:100]}...")

        # Update database with meeting name using meeting_id
        if final_summary["MeetingName"]:
            await processor.db.update_meeting_name(transcript.meeting_id, final_summary["MeetingName"])

        # Save final result
        if all_json_data:
            await processor.db.update_process(process_id, status="completed", result=json.dumps(final_summary))
            logger.info(f"Background processing completed for process_id: {process_id}")
        else:
            error_msg = "Summary generation failed: No chunks were processed successfully. Check logs for specific errors."
            await processor.db.update_process(process_id, status="failed", error=error_msg)
            logger.error(f"Background processing failed for process_id: {process_id} - {error_msg}")

    except ValueError as e:
        # Handle specific value errors (like API key issues)
        error_msg = str(e)
        logger.error(f"Configuration error in background processing for {process_id}: {error_msg}", exc_info=True)
        try:
            await processor.db.update_process(process_id, status="failed", error=error_msg)
        except Exception as db_e:
            logger.error(f"Failed to update DB status to failed for {process_id}: {db_e}", exc_info=True)
    except Exception as e:
        # Handle all other exceptions
        error_msg = f"Processing error: {str(e)}"
        logger.error(f"Error in background processing for {process_id}: {error_msg}", exc_info=True)
        try:
            await processor.db.update_process(process_id, status="failed", error=error_msg)
        except Exception as db_e:
            logger.error(f"Failed to update DB status to failed for {process_id}: {db_e}", exc_info=True)

@app.post("/process-transcript")
async def process_transcript_api(
    transcript: TranscriptRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Process a transcript text with background processing"""
    try:
        # 0. Ensure meeting exists and check permissions
        meeting = await db.get_meeting(transcript.meeting_id)
        if not meeting:
            # New Meeting: Claim Ownership
            await db.save_meeting(
                meeting_id=transcript.meeting_id,
                title="Untitled Meeting", # Default title
                owner_id=current_user.email,
                workspace_id=None # Defaults to Personal
            )
            logger.info(f"Created new meeting {transcript.meeting_id} for owner {current_user.email}")
        else:
            # Existing Meeting: Check Edit Permission
            if not await rbac.can(current_user, 'edit', transcript.meeting_id):
                raise HTTPException(status_code=403, detail="Permission denied to edit this meeting")

        # Create new process linked to meeting_id
        process_id = await processor.db.create_process(transcript.meeting_id)

        # Save transcript data associated with meeting_id
        await processor.db.save_transcript(
            transcript.meeting_id,
            transcript.text,
            transcript.model,
            transcript.model_name,
            transcript.chunk_size,
            transcript.overlap
        )

        # Use template-specific prompt if templateId is provided, otherwise use custom_prompt
        custom_prompt = transcript.custom_prompt
        if hasattr(transcript, 'templateId') and transcript.templateId and not custom_prompt:
            custom_prompt = get_template_prompt(transcript.templateId)

        # Start background processing
        background_tasks.add_task(
            process_transcript_background,
            process_id,
            transcript,
            custom_prompt,
            current_user.email
        )

        return JSONResponse({
            "message": "Processing started",
            "process_id": process_id
        })

    except Exception as e:
        logger.error(f"Error in process_transcript_api: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-detailed-notes")
async def generate_detailed_notes(request: GenerateNotesRequest, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """
    Generates detailed meeting notes using Gemini, saves them, and returns the result.
    This is intended for automatic, high-quality note generation post-meeting.
    Uses templates for structured output based on meeting type.
    """
    try:
        if not await rbac.can(current_user, 'ai_interact', request.meeting_id):
            raise HTTPException(status_code=403, detail="Permission denied to generate notes")

        logger.info(f"Generating detailed notes for meeting {request.meeting_id} using template {request.template_id}")

        # 1. Fetch meeting transcripts from the database
        meeting_data = await db.get_meeting(request.meeting_id)
        if not meeting_data or not meeting_data.get('transcripts'):
            raise HTTPException(status_code=404, detail="Meeting or transcripts not found.")

        transcripts = meeting_data['transcripts']
        full_transcript_text = "\n".join([t['text'] for t in transcripts])

        if not full_transcript_text.strip():
            raise HTTPException(status_code=400, detail="Transcript text is empty.")

        meeting_title = meeting_data.get('title', 'Untitled Meeting')
        
        # 2. Start background processing (non-blocking)
        background_tasks.add_task(
            generate_notes_with_gemini_background,
            request.meeting_id,
            full_transcript_text,
            request.template_id,
            meeting_title,
            "", # custom_context
            current_user.email
        )

        return JSONResponse(content={
            "message": "Notes generation started",
            "meeting_id": request.meeting_id,
            "template_id": request.template_id,
            "status": "processing"
        })

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error starting notes generation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/meetings/{meeting_id}/generate-notes")
async def generate_notes_for_meeting(meeting_id: str, request: GenerateNotesRequest = None, background_tasks: BackgroundTasks = None, current_user: User = Depends(get_current_user)):
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
    if not await rbac.can(current_user, 'ai_interact', meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to generate notes")

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
        
        logger.info(f"Generating notes for meeting {actual_meeting_id} using template {template_id}")

        # 1. Fetch meeting transcripts from the database
        meeting_data = await db.get_meeting(actual_meeting_id)
        if not meeting_data or not meeting_data.get('transcripts'):
            raise HTTPException(status_code=404, detail="Meeting or transcripts not found.")

        transcripts = meeting_data['transcripts']
        full_transcript_text = "\n".join([t['text'] for t in transcripts])

        if not full_transcript_text.strip():
            raise HTTPException(status_code=400, detail="Transcript text is empty.")

        meeting_title = meeting_data.get('title', 'Untitled Meeting')
        
        # 2. Start background processing (non-blocking)
        background_tasks.add_task(
            generate_notes_with_gemini_background,
            actual_meeting_id,
            full_transcript_text,
            template_id,
            meeting_title,
            custom_context,
            current_user.email
        )

        return JSONResponse(content={
            "message": "Notes generation started",
            "meeting_id": actual_meeting_id,
            "template_id": template_id,
            "status": "processing"
        })

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error starting notes generation for meeting {meeting_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat-meeting")
async def chat_meeting(request: ChatRequest, current_user: User = Depends(get_current_user)):
    """
    Chat with a specific meeting using AI.
    Streams the response back to the client.
    """
    if not await rbac.can(current_user, 'ai_interact', request.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to chat with this meeting")

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
                transcripts = meeting_data.get('transcripts', [])
                if not transcripts:
                     # Try getting from transcript_chunks if individual transcripts are empty (fallback)
                    chunk_data = await db.get_transcript_data(request.meeting_id)
                    if chunk_data and chunk_data.get("transcript"): 
                         full_text = chunk_data.get("transcript")
                    elif chunk_data and chunk_data.get("transcript_text"): 
                         full_text = chunk_data.get("transcript_text")
                else:
                    # Join all transcript segments
                    full_text = "\n".join([t['text'] for t in transcripts])
            else:
                 # If meeting not found in DB and no context provided, we just have empty context.
                 # We don't 404 here because the user might just want to chat with history/other meetings.
                 logger.warning(f"Meeting {request.meeting_id} not found in DB and no context provided.")

        # FIX: Allow proceeding if we have cross-meeting context (allowed_meeting_ids) OR if it's a general question
        # The prompt will handle empty context.
        if not full_text and not request.allowed_meeting_ids and not request.history:
             # Only block if we truly have NOTHING to go on (no context, no linked search, no history)
             # But actually, users might just want to say "Hi". So we should arguably always allow it.
             # However, to preserve original intent of "No transcript", we'll keep it soft.
             logger.info("No context, history, or linked meetings. Proceeding with empty context.")

        # 3. Stream response using TranscriptProcessor
        stream_generator = await processor.transcript_processor.chat_about_meeting(
            context=full_text,
            question=request.question,
            model=request.model,
            model_name=request.model_name,
            allowed_meeting_ids=request.allowed_meeting_ids,
            history=request.history,
            user_email=current_user.email
        )

        return StreamingResponse(stream_generator, media_type="text/plain")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat_meeting: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/catch-up")
async def catch_up(request: CatchUpRequest, current_user: User = Depends(get_current_user)):
    """
    Generate a quick bulleted summary of the meeting so far.
    For late joiners or participants who zoned out.
    Streams the response back for fast display.
    """
    try:
        logger.info(f"Catch-up request received with {len(request.transcripts)} transcripts")
        
        # Join all transcripts
        full_text = "\n".join(request.transcripts)
        
        if not full_text or len(full_text.strip()) < 10:
            return JSONResponse(
                status_code=400,
                content={"error": "Not enough transcript content to summarize yet."}
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
                    api_key = await db.get_api_key("groq", user_email=current_user.email)
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
                    api_key = await db.get_api_key("gemini", user_email=current_user.email)
                    if not api_key:
                        import os
                        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                    if not api_key:
                        yield "Error: Gemini API key not configured"
                        return

                    import google.generativeai as genai
                    genai.configure(api_key=api_key)
                    
                    # Ensure properly named model
                    model_name = request.model_name
                    if not model_name.startswith("gemini-"):
                         model_name = f"gemini-{model_name}" if "gemini" not in model_name else model_name
                    
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
async def refine_notes(request: RefineNotesRequest, current_user: User = Depends(get_current_user)):
    """
    Refine existing meeting notes based on user instructions and transcript context.
    Streams the refined notes back.
    """
    if not await rbac.can(current_user, 'ai_interact', request.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to refine notes")

    try:
        logger.info(f"Refining notes for meeting {request.meeting_id} with instruction: {request.user_instruction[:50]}...")

        # 1. Fetch meeting transcripts for context
        meeting_data = await db.get_meeting(request.meeting_id)
        full_transcript = ""
        if meeting_data and meeting_data.get('transcripts'):
             full_transcript = "\n".join([t['text'] for t in meeting_data['transcripts']])

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
                    api_key = await db.get_api_key("groq", user_email=current_user.email)
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
                    api_key = await db.get_api_key("gemini", user_email=current_user.email)
                    if not api_key:
                        import os
                        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                    if not api_key:
                        yield "Error: Gemini API key not configured"
                        return

                    import google.generativeai as genai
                    genai.configure(api_key=api_key)
                    
                    # Ensure properly named model
                    model_name = request.model_name
                    if not model_name.startswith("gemini-"):
                         model_name = f"gemini-{model_name}" if "gemini" not in model_name else model_name
                    
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
        from vector_store import search_context, get_collection_stats
        
        # Check if vector store is available
        stats = get_collection_stats()
        if stats.get("status") != "available":
            return JSONResponse(
                status_code=503,
                content={"error": "Vector store not available", "results": []}
            )
        
        # Perform search
        results = await search_context(
            query=request.query,
            n_results=request.n_results,
            allowed_meeting_ids=request.allowed_meeting_ids
        )
        
        return {
            "status": "success",
            "query": request.query,
            "results": results,
            "total_indexed": stats.get("count", 0)
        }
        
    except Exception as e:
        logger.error(f"Error in search_context: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get-summary/{meeting_id}")
async def get_summary(meeting_id: str, current_user: User = Depends(get_current_user)):
    """Get the summary for a given meeting ID"""
    if not await rbac.can(current_user, 'view', meeting_id):
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
                    "error": "Meeting ID not found"
                }
            )

        status = result.get("status", "unknown").lower()
        logger.debug(f"Summary status for meeting {meeting_id}: {status}, error: {result.get('error')}")

        # Parse result data if available
        summary_data = None
        if result.get("result"):
            try:
                parsed_result = json.loads(result["result"])
                if isinstance(parsed_result, str):
                    summary_data = json.loads(parsed_result)
                else:
                    summary_data = parsed_result
                if not isinstance(summary_data, dict):
                    logger.error(f"Parsed summary data is not a dictionary for meeting {meeting_id}")
                    summary_data = None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON data for meeting {meeting_id}: {str(e)}")
                status = "failed"
                result["error"] = f"Invalid summary data format: {str(e)}"
            except Exception as e:
                logger.error(f"Unexpected error parsing summary data for {meeting_id}: {str(e)}")
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
                logger.info(f"Passing through markdown content for meeting {meeting_id}")

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
                if backend_key in summary_data and isinstance(summary_data[backend_key], dict):
                    transformed_data[frontend_key] = summary_data[backend_key]
            
            # Add meeting notes sections if available - PRESERVE ORDER AND HANDLE DUPLICATES
            if "MeetingNotes" in summary_data and isinstance(summary_data["MeetingNotes"], dict):
                meeting_notes = summary_data["MeetingNotes"]
                if isinstance(meeting_notes.get("sections"), list):
                    # Add section order array to maintain order
                    transformed_data["_section_order"] = []
                    used_keys = set()
                    
                    for index, section in enumerate(meeting_notes["sections"]):
                        if isinstance(section, dict) and "title" in section and "blocks" in section:
                            # Ensure blocks is a list to prevent frontend errors
                            if not isinstance(section.get("blocks"), list):
                                section["blocks"] = []
                                
                            # Convert title to snake_case key
                            base_key = section["title"].lower().replace(" & ", "_").replace(" ", "_")
                            
                            # Handle duplicate section names by adding index
                            key = base_key
                            if key in used_keys:
                                key = f"{base_key}_{index}"
                            
                            used_keys.add(key)
                            transformed_data[key] = section
                            # Only add to _section_order if the section was successfully added
                            transformed_data["_section_order"].append(key)

        response = {
            "status": "processing" if status in ["processing", "pending", "started"] else status,
            "meetingName": summary_data.get("MeetingName") if isinstance(summary_data, dict) else None,
            "meeting_id": meeting_id,
            "start": result.get("start_time"),
            "end": result.get("end_time"),
            "data": transformed_data if status == "completed" else None
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
                "error": f"Internal server error: {str(e)}"
            }
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
        Focus on quick, actionable items. Keep the summary concise and scannable."""
    }
    
    return templates.get(template_id, templates["standard_meeting"])

async def generate_notes_with_gemini_background(meeting_id: str, transcript_text: str, template_id: str, meeting_title: str, custom_context: str = "", user_email: Optional[str] = None):
    """Background task to generate meeting notes using Gemini with support for long transcripts"""
    process_id = None
    try:
        logger.info(f"Starting Gemini note generation for meeting: {meeting_id} with template: {template_id}")
        
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
            await processor.db.update_process(process_id, status="failed", error=error_msg)
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
        is_long_meeting = len(transcript_text) > 100000 # ~15k-20k words
        length_guidance = ""
        if is_long_meeting:
            length_guidance = "\nNote: This is a long meeting. Please ensure the summary is comprehensive and covers the entire duration of the transcript without omitting later parts.\n"
        
        # CHUNKING LOGIC
        # Split transcript into chunks to avoid output token limits/truncation
        chunk_size = 40000 
        chunks = [transcript_text[i:i+chunk_size] for i in range(0, len(transcript_text), chunk_size)]
        
        full_markdown_notes = ""
        logger.info(f"Processing transcript in {len(chunks)} chunks (size: {chunk_size})")

        for i, chunk in enumerate(chunks):
            is_first = (i == 0)
            part_label = f"Part {i+1}/{len(chunks)}"
            
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
{'Include a main title.' if is_first else 'Do NOT include a main title (start with ## Section).'}
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
                        temperature=0.2, # Lower temperature for more factual notes
                        max_output_tokens=8192 # Ensure enough space for detailed notes
                    )
                )
                
                if not response or not response.text:
                    error_msg = f"Gemini returned empty response for chunk {i+1}"
                    logger.error(error_msg)
                    full_markdown_notes += f"\n\n[Error: Could not generate notes for {part_label}]\n\n"
                    continue
                
                full_markdown_notes += response.text.strip() + "\n\n"
            except Exception as e:
                logger.error(f"Error processing chunk {i+1}: {str(e)}")
                full_markdown_notes += f"\n\n[Error processing {part_label}: {str(e)}]\n\n"
        
        markdown_notes = full_markdown_notes.strip()
        
        # Extract meeting title if generated
        meeting_name = meeting_title
        if "Meeting Title:" in markdown_notes or "# " in markdown_notes:
            lines = markdown_notes.split('\n')
            for line in lines[:5]:  # Check first few lines
                if line.startswith('# ') and not line.startswith('## '):
                    meeting_name = line.replace('# ', '').strip()
                    break
        
        # Format the summary in the expected structure
        summary_data = {
            "markdown": markdown_notes,
            "MeetingName": meeting_name
        }
        
        # Update meeting name if different
        if meeting_name and meeting_name != meeting_title:
            await processor.db.update_meeting_name(meeting_id, meeting_name)
        
        # Save the summary
        await processor.db.update_process(process_id, status="completed", result=json.dumps(summary_data))
        logger.info(f"✅ Successfully generated notes for meeting: {meeting_id} using Gemini {model_name}")
        
    except Exception as e:
        error_msg = f"Error generating notes with Gemini: {str(e)}"
        logger.error(error_msg, exc_info=True)
        try:
            if process_id:
                await processor.db.update_process(process_id, status="failed", error=error_msg)
            else:
                # Create process just to track the failure
                process_id = await processor.db.create_process(meeting_id)
                await processor.db.update_process(process_id, status="failed", error=error_msg)
        except Exception as db_e:
            logger.error(f"Failed to update DB status to failed: {db_e}", exc_info=True)

@app.post("/save-transcript")
async def save_transcript(request: SaveTranscriptRequest, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """Save transcript segments for a meeting and automatically generate notes based on template"""
    try:
        logger.info(f"Received save-transcript request for meeting: {request.meeting_title}")
        logger.info(f"Number of transcripts to save: {len(request.transcripts)}")
        logger.info(f"Template ID: {request.template_id}")

        # Log first transcript timestamps for debugging
        if request.transcripts:
            first = request.transcripts[0]
            logger.debug(f"First transcript: audio_start_time={first.audio_start_time}, audio_end_time={first.audio_end_time}, duration={first.duration}")

        # Generate a unique meeting ID
        meeting_id = f"meeting-{int(time.time() * 1000)}"

        # Save the meeting with folder path (if provided) and owner
        await db.save_meeting(meeting_id, request.meeting_title, folder_path=request.folder_path, owner_id=current_user.email)

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
                duration=transcript.duration
            )
            full_transcript_text += transcript.text + "\n"

        logger.info("Transcripts saved successfully")
        
        # Store embeddings for cross-meeting search
        try:
            from vector_store import store_meeting_embeddings
            transcript_dicts = [{"text": t.text, "timestamp": t.timestamp} for t in request.transcripts]
            chunks_stored = await store_meeting_embeddings(
                meeting_id=meeting_id,
                meeting_title=request.meeting_title,
                meeting_date=datetime.now().isoformat(),
                transcripts=transcript_dicts
            )
            logger.info(f"✅ Stored {chunks_stored} embedding chunks for cross-meeting search")
        except Exception as e:
            logger.warning(f"⚠️ Failed to store embeddings (non-critical): {e}")
        
        # Automatically trigger note generation using Gemini
        if full_transcript_text.strip():
            try:
                logger.info(f"Auto-generating notes with Gemini using template: {request.template_id}")
                
                # Use Gemini for note generation (always use Gemini as specified)
                background_tasks.add_task(
                    generate_notes_with_gemini_background,
                    meeting_id,
                    full_transcript_text,
                    request.template_id or "standard_meeting",
                    request.meeting_title,
                    "", # custom_context
                    current_user.email
                )
                logger.info(f"Started automatic note generation with Gemini for meeting: {meeting_id}")
            except Exception as e:
                logger.error(f"Error starting automatic note generation: {str(e)}", exc_info=True)
                # Don't fail the save if auto-generation fails
        
        return {"status": "success", "message": "Transcript saved successfully", "meeting_id": meeting_id}
    except Exception as e:
        logger.error(f"Error saving transcript: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get-model-config")
async def get_model_config(current_user: User = Depends(get_current_user)):
    """Get the current model configuration"""
    model_config = await db.get_model_config()
    if model_config:
        api_key = await db.get_api_key(model_config["provider"], user_email=current_user.email)
        if api_key != None:
            model_config["apiKey"] = api_key
    return model_config

@app.post("/save-model-config")
async def save_model_config(request: SaveModelConfigRequest, current_user: User = Depends(get_current_user)):
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
        transcript_api_key = await db.get_transcript_api_key(transcript_config["provider"], user_email=current_user.email)
        if transcript_api_key != None:
            transcript_config["apiKey"] = transcript_api_key
    return transcript_config

@app.post("/save-transcript-config")
async def save_transcript_config(request: SaveTranscriptConfigRequest):
    """Save the transcript configuration"""
    await db.save_transcript_config(request.provider, request.model)
    if request.apiKey != None:
        await db.save_transcript_api_key(request.apiKey, request.provider)
    return {"status": "success", "message": "Transcript configuration saved successfully"}

class GetApiKeyRequest(BaseModel):
    provider: str

@app.post("/get-api-key")
async def get_api_key_api(request: GetApiKeyRequest, current_user: User = Depends(get_current_user)):
    try:
        return await db.get_api_key(request.provider, user_email=current_user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get-transcript-api-key")
async def get_transcript_api_key_api(request: GetApiKeyRequest, current_user: User = Depends(get_current_user)):
    try:
        return await db.get_transcript_api_key(request.provider, user_email=current_user.email)
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
async def save_user_key(request: UserApiKeySaveRequest, current_user: User = Depends(get_current_user)):
    """Save/Update an encrypted API key for the current user"""
    try:
        await db.save_user_api_key(current_user.email, request.provider, request.api_key)
        return {"status": "success", "message": f"API key for {request.provider} saved"}
    except Exception as e:
        logger.error(f"Error saving user key: {e}")
        raise HTTPException(status_code=500, detail="Failed to save key")

@app.delete("/api/user/keys/{provider}")
async def delete_user_key(provider: str, current_user: User = Depends(get_current_user)):
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

@app.websocket("/ws/streaming-audio")
async def websocket_streaming_audio(websocket: WebSocket, session_id: Optional[str] = None, user_email: Optional[str] = None):
    """
    Real-time streaming transcription with Groq Whisper Large v3.

    HYBRID MODE:
    - VAD detects natural speech pauses (for coherent sentences)
    - Max-wait timer forces transcription after 8s of continuous speech
    - 4s buffer with 3s processing interval
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
        
        # Only use user-provided Groq API key (no system fallback)
        groq_api_key = await db.get_user_api_key(user_email, "groq") if user_email else None

        if not groq_api_key:
            logger.warning(f"[Streaming] No personal Groq API key for user: {user_email}")
            await websocket.send_json({
                "type": "error",
                "code": "GROQ_KEY_REQUIRED",
                "message": "Groq API key required. Please add your Groq API key in Settings → Personal Keys."
            })
            await websocket.close()
            return
        
        manager = StreamingTranscriptionManager(groq_api_key)
        streaming_managers[session_id] = manager
        logger.info(f"[Streaming] ✅ Session {session_id} started (HYBRID mode)")

    # Send connection confirmation
    await websocket.send_json({
        "type": "connected",
        "session_id": session_id,
        "message": "Groq streaming ready (HYBRID mode)",
        "timestamp": datetime.utcnow().isoformat()
    })

    # Define callbacks for partial and final transcripts
    async def on_partial(data):
        """Send partial (gray, updating) transcript to browser"""
        await websocket.send_json({
            "type": "partial",
            "text": data["text"],
            "confidence": data["confidence"],
            "is_stable": data.get("is_stable", False),
            "timestamp": datetime.utcnow().isoformat()
        })
        logger.debug(f"[Streaming] Partial: {data['text'][:50]}...")

    async def on_final(data):
        """Send final (black, locked) transcript to browser"""
        response = {
            "type": "final",
            "text": data["text"],
            "confidence": data["confidence"],
            "reason": data.get("reason", "unknown"),
            "timestamp": datetime.utcnow().isoformat()
        }

        # Include translation metadata if available
        if data.get("original_text"):
            response["original_text"] = data["original_text"]
            response["translated"] = data.get("translated", False)

        await websocket.send_json(response)

        # Log with translation info
        if data.get("translated"):
            logger.info(f"[Streaming] Final (EN): {data['text'][:50]}... (HI: {data.get('original_text', '')[:30]}...)")
        else:
            logger.info(f"[Streaming] Final: {data['text'][:50]}... (reason: {data.get('reason')})")

    async def on_error(message: str):
        """Send error message to browser"""
        await websocket.send_json({
            "type": "error",
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        })
        logger.warning(f"[Streaming] Error sent to client: {message}")

    try:
        chunk_count = 0

        while True:
            # Receive PCM audio chunk (continuous stream)
            audio_chunk = await websocket.receive_bytes()
            chunk_count += 1

            if chunk_count % 50 == 0:  # Log every 50 chunks (~5s)
                stats = manager.get_stats()
                logger.debug(
                    f"[Streaming] Session {session_id}: "
                    f"chunks={chunk_count}, transcriptions={stats['transcriptions']}, "
                    f"speaking={stats['is_speaking']}"
                )

            # Process with VAD + Groq
            await manager.process_audio_chunk(
                audio_data=audio_chunk,
                on_partial=on_partial,
                on_final=on_final,
                on_error=on_error
            )

    except WebSocketDisconnect:
        logger.info(f"[Streaming] Session {session_id} disconnected by client")

    except Exception as e:
        logger.error(
            f"[Streaming] Error in session {session_id}: {str(e)}",
            exc_info=True
        )
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })
        except:
            pass

    finally:
        # Cleanup
        if session_id in streaming_managers:
            manager = streaming_managers[session_id]
            manager.cleanup()
            del streaming_managers[session_id]

        logger.info(f"[Streaming] Session {session_id} cleaned up")


@app.get("/list-meetings")
async def list_meetings():
    """List all available meetings with basic metadata."""
    try:
        meetings = await db.get_all_meetings()
        return [
            {
                "id": m["id"],
                "title": m["title"],
                "date": m["created_at"] # get_all_meetings returns 'created_at'
            }
            for m in meetings
        ]
    except Exception as e:
        logger.error(f"Error listing meetings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/reindex-all")
async def reindex_all():
    """Admin endpoint to re-index all past meetings into ChromaDB."""
    try:
        from vector_store import store_meeting_embeddings
        
        # 1. Fetch all meetings
        meetings = await db.get_all_meetings()
        logger.info(f"Re-indexing {len(meetings)} meetings...")
        
        count = 0
        successful = 0
        failed = 0
        
        for m in meetings:
            meeting_id = m["id"]
            
            try:
                # 2. Get full details including transcripts
                meeting_data = await db.get_meeting(meeting_id)
                if not meeting_data or not meeting_data.get("transcripts"):
                    logger.info(f"Skipping {meeting_id}: no transcripts")
                    continue
                    
                # 3. Store in vector DB (sequential processing to avoid ChromaDB race conditions)
                num_chunks = await store_meeting_embeddings(
                    meeting_id=meeting_id,
                    meeting_title=meeting_data.get("title", "Untitled"),
                    meeting_date=meeting_data.get("created_at", ""),
                    transcripts=meeting_data.get("transcripts", [])
                )
                
                if num_chunks > 0:
                    successful += 1
                    logger.info(f"✅ Indexed meeting {meeting_id}: {num_chunks} chunks")
                else:
                    logger.warning(f"⚠️ Meeting {meeting_id} indexed but produced 0 chunks")
                
                count += 1
                
                # Small delay to ensure ChromaDB processes fully before next meeting
                await asyncio.sleep(0.05)
                
            except Exception as e:
                failed += 1
                logger.error(f"❌ Failed to index meeting {meeting_id}: {e}")
                continue  # Continue with next meeting even if one fails
            
        return {"status": "success", "indexed_count": count}
        
    except Exception as e:
        logger.error(f"Re-indexing failed: {e}")
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

        logger.info("Successfully cleaned up resources")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}", exc_info=True)

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    uvicorn.run("main:app", host="0.0.0.0", port=5167, reload=True)