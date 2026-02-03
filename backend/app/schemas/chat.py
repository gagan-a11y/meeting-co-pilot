from pydantic import BaseModel
from typing import List, Optional, Dict


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
    model_name: str = "gemini-2.5-flash"


class SearchContextRequest(BaseModel):
    """Request model for cross-meeting context search"""

    query: str
    n_results: int = 5
    allowed_meeting_ids: Optional[List[str]] = None  # None = search all meetings
