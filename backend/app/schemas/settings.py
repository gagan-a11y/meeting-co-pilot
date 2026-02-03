from pydantic import BaseModel
from typing import Optional


class SaveModelConfigRequest(BaseModel):
    provider: str
    model: str
    whisperModel: str
    apiKey: Optional[str] = None


class SaveTranscriptConfigRequest(BaseModel):
    provider: str
    model: str
    apiKey: Optional[str] = None


class GetApiKeyRequest(BaseModel):
    provider: str


class UserApiKeySaveRequest(BaseModel):
    provider: str
    api_key: str
