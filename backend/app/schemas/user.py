from pydantic import BaseModel
from typing import Optional


class User(BaseModel):
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    # We can add efficient role/org checking here later
    # role: str = "user"
