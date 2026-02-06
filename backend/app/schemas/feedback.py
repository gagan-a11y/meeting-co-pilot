from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class FeedbackCreate(BaseModel):
    type: Literal["bug", "feature", "general"] = Field(
        ..., description="Type of feedback"
    )
    title: str = Field(..., min_length=5, max_length=200, description="Short summary")
    description: Optional[str] = Field(None, description="Detailed explanation")


class FeedbackUpdateStatus(BaseModel):
    status: Literal["pending", "in_review", "in_progress", "completed", "rejected"]


class FeedbackResponse(BaseModel):
    id: str
    user_id: str
    user_email: str
    type: str
    title: str
    description: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
