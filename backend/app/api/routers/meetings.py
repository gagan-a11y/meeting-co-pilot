from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Robust Import Strategy
try:
    from ..deps import get_current_user
    from ...schemas.user import User
    from ...schemas.meeting import (
        MeetingResponse,
        MeetingDetailsResponse,
        MeetingTitleUpdate,
        DeleteMeetingRequest,
    )
    from ...db import DatabaseManager
    from ...core.rbac import RBAC
    from ...services.storage import StorageService
except (ImportError, ValueError):
    from api.deps import get_current_user
    from schemas.user import User
    from schemas.meeting import (
        MeetingResponse,
        MeetingDetailsResponse,
        MeetingTitleUpdate,
        DeleteMeetingRequest,
    )
    from db import DatabaseManager
    from core.rbac import RBAC
    from services.storage import StorageService

# Initialize DB and RBAC
db = DatabaseManager()
rbac = RBAC(db)


@router.get("/get-meetings", response_model=List[MeetingResponse])
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


@router.get("/get-meeting/{meeting_id}", response_model=MeetingDetailsResponse)
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


@router.post("/save-meeting-title")
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


@router.post("/delete-meeting")
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
        # Delete audio file from Storage (Local or GCP)
        try:
            await StorageService.delete_file(f"{data.meeting_id}/recording.wav")
            # Remove any remaining artifacts under the meeting prefix (chunks, metadata, etc.)
            await StorageService.delete_prefix(f"{data.meeting_id}/")
        except Exception as e:
            logger.warning(f"Failed to delete audio file for {data.meeting_id}: {e}")

        success = await db.delete_meeting(data.meeting_id)
        if success:
            return {"message": "Meeting deleted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete meeting")
    except Exception as e:
        logger.error(f"Error deleting meeting: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list-meetings")
async def list_meetings(current_user: User = Depends(get_current_user)):
    """List meetings visible to the current user with basic metadata."""
    try:
        accessible_ids = await rbac.get_accessible_meetings(current_user)
        meetings = await db.get_all_meetings()
        visible_meetings = [m for m in meetings if m["id"] in accessible_ids]
        return [
            {
                "id": m["id"],
                "title": m["title"],
                "date": m["created_at"],  # get_all_meetings returns 'created_at'
            }
            for m in visible_meetings
        ]
    except Exception as e:
        logger.error(f"Error listing meetings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
