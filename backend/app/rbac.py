from db import DatabaseManager
from auth import User
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class RBAC:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def can(self, user: User, action: str, meeting_id: str) -> bool:
        """
        Central Policy Check: Can `user` perform `action` on `meeting_id`?
        
        Actions: 'view', 'edit', 'delete', 'invite', 'ai_interact'
        """
        if not user or not user.email:
            return False

        # Allow AI interaction with the current recording (not yet saved in DB)
        if meeting_id == 'current-recording' and action == 'ai_interact':
            return True

        # 1. Fetch meeting context (Owner, Workspace)
        # We use a lightweight query instead of get_meeting to save bandwidth
        try:
            async with self.db._get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT owner_id, workspace_id FROM meetings WHERE id = ?", 
                    (meeting_id,)
                )
                row = await cursor.fetchone()
                
                if not row:
                    if action in ['ai_interact', 'view']:
                        logger.warning(f"RBAC: Meeting {meeting_id} not found in DB, but allowing '{action}' (assuming new/temp meeting)")
                        return True
                    logger.warning(f"RBAC: Meeting {meeting_id} not found")
                    return False
                    
                owner_id, workspace_id = row
            
            logger.info(f"RBAC Check: user={user.email}, action={action}, meeting={meeting_id}, owner={owner_id}")
            
            # 2. Check Ownership (ALLOW ALL)
            # LEGACY SUPPORT: If owner_id is None, allow access (for migration/corrupted records)
            if owner_id is None or owner_id == user.email or owner_id == "":
                return True
        except Exception as e:
            logger.error(f"RBAC Error during lookup: {str(e)}")
            # Fallback for transient errors: allow ai_interact if it's the current user
            if action == 'ai_interact':
                return True
            return False

        # 3. Check Workspace Admin (ALLOW ALL)
        if workspace_id:
            try:
                async with self.db._get_connection() as conn:
                    cursor = await conn.execute(
                        "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                        (workspace_id, user.email)
                    )
                    member_row = await cursor.fetchone()
                    if member_row and member_row[0] == 'admin':
                        return True
            except Exception as e:
                logger.error(f"RBAC Workspace check error: {str(e)}")

        # 4. Check Explicit Permissions
        try:
            async with self.db._get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT role FROM meeting_permissions WHERE meeting_id = ? AND user_id = ?",
                    (meeting_id, user.email)
                )
                perm_row = await cursor.fetchone()
            
            if not perm_row:
                return False
            
            role = perm_row[0]
            
            # 5. Resolve based on Role & Action
            # viewer: view
            # participant: view, ai_interact, edit
            
            if role == 'viewer':
                if action in ['view', 'export']:
                    return True
                return False
            
            if role == 'participant':
                if action in ['view', 'export', 'ai_interact', 'edit']:
                    return True
                # Participants cannot delete or invite (unless logic changes)
                return False
        except Exception as e:
            logger.error(f"RBAC Permission check error: {str(e)}")
            return False

        return False

    async def get_accessible_meetings(self, user: User):
        """
        Return a list of meeting_ids the user can access.
        Used for filtering /get-meetings.
        """
        # Complex query logic needed here or just filter in memory?
        # SQL filtering is better.
        
        # Query:
        # 1. Owned meetings
        # 2. Workspace meetings where user is ADMIN
        # 3. Workspace meetings where user is MEMBER (Wait, members don't see all. ONLY Explicit invites!)
        #    Actually, Spec says: "workspace_member sees only meetings they’re invited to".
        #    So Workspace Membership (Role=Member) gives NO default access.
        #    Workspace Admin gives ALL access.
        # 4. Explicitly invited meetings (Personal or Workspace) via meeting_permissions.
        
        query = """
            SELECT m.id 
            FROM meetings m
            LEFT JOIN workspace_members wm ON m.workspace_id = wm.workspace_id AND wm.user_id = ?
            LEFT JOIN meeting_permissions mp ON m.id = mp.meeting_id AND mp.user_id = ?
            WHERE 
                m.owner_id = ?                  -- 1. Owner
                OR m.owner_id IS NULL           -- 1b. Legacy (No owner)
                OR (wm.role = 'admin')          -- 2. Workspace Admin
                OR (mp.role IS NOT NULL)        -- 3. Explicit Invite
        """
        # Note: If meeting has NO workspace_id (Personal), wm.role will be null.
        
        accessible_ids = []
        async with self.db._get_connection() as conn:
            cursor = await conn.execute(query, (user.email, user.email, user.email))
            rows = await cursor.fetchall()
            accessible_ids = [r[0] for r in rows]
            
        return accessible_ids