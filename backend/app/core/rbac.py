try:
    from ..db import DatabaseManager
    from ..schemas.user import User
except (ImportError, ValueError):
    from db import DatabaseManager
    from schemas.user import User

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RBAC:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def can(self, user: User, action: str, meeting_id: str) -> bool:
        """
        Central Policy Check: Can `user` perform `action` on `meeting_id`?

        PERMISSIVE MODE ENABLED: Any authenticated user has full access.
        """
        if not user or not user.email:
            return False

        # Allow AI interaction with the current recording (not yet saved in DB)
        if meeting_id == "current-recording" and action == "ai_interact":
            return True

        # In permissive mode, we trust authenticated users
        logger.info(
            f"RBAC Permissive Check: Allowing {user.email} to {action} {meeting_id}"
        )
        return True

    async def get_accessible_meetings(self, user: User):
        """
        Return a list of meeting_ids the user can access.

        PERMISSIVE MODE ENABLED: Returns ALL meetings.
        """
        # Return all meeting IDs so the user sees everything
        async with self.db._get_connection() as conn:
            rows = await conn.fetch("SELECT id FROM meetings")
            accessible_ids = [r["id"] for r in rows]

        return accessible_ids
