from pydantic import BaseModel
from typing import List, Literal, Optional


class Block(BaseModel):
    """Represents a block of content in a section."""

    id: str
    type: Literal["bullet", "heading1", "heading2", "text"]
    content: str
    color: str  # Frontend currently only uses 'gray' or default


class Section(BaseModel):
    """Represents a section in the meeting summary"""

    title: str
    blocks: List[Block]


class MeetingNotes(BaseModel):
    """Represents the meeting notes"""

    meeting_name: str
    sections: List[Section] = []


class People(BaseModel):
    """Represents the people in the meeting."""

    title: str
    blocks: List[Block] = []


class SummaryResponse(BaseModel):
    """Represents the meeting summary response based on a section of the transcript"""

    MeetingName: Optional[str] = "Untitled Meeting"
    # Using forward references as string because classes are defined above but referenced here
    People: Optional["People"] = None
    SessionSummary: Optional[Section] = None
    CriticalDeadlines: Optional[Section] = None
    KeyItemsDecisions: Optional[Section] = None
    ImmediateActionItems: Optional[Section] = None
    NextSteps: Optional[Section] = None
    MeetingNotes: Optional["MeetingNotes"] = None
