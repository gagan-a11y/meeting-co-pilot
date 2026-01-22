import asyncpg
import json
import os
from datetime import datetime
from typing import Optional, Dict
import logging
from contextlib import asynccontextmanager

try:
    from .encryption import encrypt_key, decrypt_key
except ImportError:
    from encryption import encrypt_key, decrypt_key

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_url: str = None):
        if db_url is None:
            # Default to the provided Neon URL if not in env, but env is preferred
            default_url = "postgresql://neondb_owner:npg_3JYK7ySezjrT@ep-morning-truth-ahrz730e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require"
            self.db_url = os.getenv('DATABASE_URL', default_url)
        else:
            self.db_url = db_url
            
        # No more local init_db or schema validation on app startup
        # We assume the migration script has run or the DB is provisioned

    @asynccontextmanager
    async def _get_connection(self):
        """Get a new database connection from the pool"""
        # In a real prod app, you'd want a global pool created on startup
        # For now, creating a connection per request is okay for low traffic, 
        # but we should move to a pool pattern in main.py startup event later.
        conn = await asyncpg.connect(self.db_url)
        try:
            yield conn
        finally:
            await conn.close()

    async def create_process(self, meeting_id: str) -> str:
        """Create a new process entry or update existing one and return its ID"""
        now = datetime.utcnow() # Postgres expects datetime object, not string
        
        try:
            async with self._get_connection() as conn:
                async with conn.transaction():
                    # Upsert logic for Postgres
                    # Try update first
                    result = await conn.execute(
                        """
                        UPDATE summary_processes 
                        SET status = $1, updated_at = $2, start_time = $3, error = NULL, result = NULL
                        WHERE meeting_id = $4
                        """,
                        "PENDING", now, now, meeting_id
                    )
                    
                    # Check if update happened (asyncpg returns "UPDATE N")
                    if result == "UPDATE 0":
                        await conn.execute(
                            """
                            INSERT INTO summary_processes (meeting_id, status, created_at, updated_at, start_time) 
                            VALUES ($1, $2, $3, $4, $5)
                            """,
                            meeting_id, "PENDING", now, now, now
                        )
                    
                    logger.info(f"Successfully created/updated process for meeting_id: {meeting_id}")
                    
        except Exception as e:
            logger.error(f"Database connection error in create_process: {str(e)}", exc_info=True)
            raise
        
        return meeting_id

    async def update_process(self, meeting_id: str, status: str, result: Optional[Dict] = None, error: Optional[str] = None, 
                           chunk_count: Optional[int] = None, processing_time: Optional[float] = None, 
                           metadata: Optional[Dict] = None):
        """Update a process status and result"""
        now = datetime.utcnow()
        
        try:
            async with self._get_connection() as conn:
                async with conn.transaction():
                    update_fields = ["status = $1", "updated_at = $2"]
                    params = [status, now]
                    param_idx = 3 # Start at $3
                    
                    if result:
                        # Postgres JSONB handles dicts natively with asyncpg
                        update_fields.append(f"result = ${param_idx}")
                        params.append(json.dumps(result)) # Store as JSON string for JSONB
                        param_idx += 1
                            
                    if error:
                        sanitized_error = str(error).replace('\n', ' ').replace('\r', '')[:1000]
                        update_fields.append(f"error = ${param_idx}")
                        params.append(sanitized_error)
                        param_idx += 1
                        
                    if chunk_count is not None:
                        update_fields.append(f"chunk_count = ${param_idx}")
                        params.append(chunk_count)
                        param_idx += 1
                        
                    if processing_time is not None:
                        update_fields.append(f"processing_time = ${param_idx}")
                        params.append(processing_time)
                        param_idx += 1
                        
                    if metadata:
                        update_fields.append(f"metadata = ${param_idx}")
                        params.append(json.dumps(metadata))
                        param_idx += 1
                            
                    if status.upper() in ['COMPLETED', 'FAILED']:
                        update_fields.append(f"end_time = ${param_idx}")
                        params.append(now)
                        param_idx += 1
                        
                    params.append(meeting_id)
                    query = f"UPDATE summary_processes SET {', '.join(update_fields)} WHERE meeting_id = ${param_idx}"
                    
                    res = await conn.execute(query, *params)
                    if res == "UPDATE 0":
                        logger.warning(f"No process found to update for meeting_id: {meeting_id}")
                        
                    logger.debug(f"Successfully updated process status to {status} for meeting_id: {meeting_id}")
                    
        except Exception as e:
            logger.error(f"Database connection error in update_process: {str(e)}", exc_info=True)
            raise

    async def save_transcript(self, meeting_id: str, transcript_text: str, model: str, model_name: str, 
                            chunk_size: int, overlap: int):
        """Save transcript data"""
        if not meeting_id or not meeting_id.strip():
            raise ValueError("meeting_id cannot be empty")
        if not transcript_text or not transcript_text.strip():
            raise ValueError("transcript_text cannot be empty")
            
        now = datetime.utcnow()
        
        try:
            async with self._get_connection() as conn:
                async with conn.transaction():
                    # Postgres upsert using ON CONFLICT
                    await conn.execute("""
                        INSERT INTO full_transcripts (meeting_id, transcript_text, model, model_name, chunk_size, overlap, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (meeting_id) 
                        DO UPDATE SET 
                            transcript_text = EXCLUDED.transcript_text,
                            model = EXCLUDED.model,
                            model_name = EXCLUDED.model_name,
                            chunk_size = EXCLUDED.chunk_size,
                            overlap = EXCLUDED.overlap,
                            created_at = EXCLUDED.created_at
                    """, meeting_id, transcript_text, model, model_name, chunk_size, overlap, now)
                    
                    logger.info(f"Successfully saved transcript for meeting_id: {meeting_id} (size: {len(transcript_text)} chars)")
                    
        except Exception as e:
            logger.error(f"Database connection error in save_transcript: {str(e)}", exc_info=True)
            raise

    async def update_meeting_name(self, meeting_id: str, meeting_name: str):
        """Update meeting name in both meetings and full_transcripts tables"""
        now = datetime.utcnow()
        async with self._get_connection() as conn:
            async with conn.transaction():
                await conn.execute("""
                    UPDATE meetings
                    SET title = $1, updated_at = $2
                    WHERE id = $3
                """, meeting_name, now, meeting_id)
                
                await conn.execute("""
                    UPDATE full_transcripts
                    SET meeting_name = $1
                    WHERE meeting_id = $2
                """, meeting_name, meeting_id)

    async def get_transcript_data(self, meeting_id: str):
        """Get transcript/summary process data for a meeting"""
        async with self._get_connection() as conn:
            row = await conn.fetchrow("""
                SELECT meeting_id, status, result, error, start_time, end_time
                FROM summary_processes 
                WHERE meeting_id = $1
                ORDER BY start_time DESC
                LIMIT 1
            """, meeting_id)
            
            if row:
                # Convert Record to dict
                data = dict(row)
                # Handle JSONB fields if they are strings (asyncpg might return dict directly if jsonb)
                if isinstance(data.get('result'), str):
                    try:
                        data['result'] = json.loads(data['result'])
                    except: pass
                return data
            return None

    async def save_meeting(self, meeting_id: str, title: str, folder_path: str = None, owner_id: str = None, workspace_id: str = None):
        """Save or update a meeting"""
        try:
            async with self._get_connection() as conn:
                # Check existence
                exists = await conn.fetchval("SELECT id FROM meetings WHERE id = $1", meeting_id)

                if not exists:
                    now = datetime.utcnow()
                    await conn.execute("""
                        INSERT INTO meetings (id, title, created_at, updated_at, folder_path, owner_id, workspace_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """, meeting_id, title, now, now, folder_path, owner_id, workspace_id)
                    logger.info(f"Saved meeting {meeting_id} (Owner: {owner_id}, WS: {workspace_id})")
                else:
                    # Optional: We could update title here if we wanted
                    pass
                return True
        except Exception as e:
            logger.error(f"Error saving meeting: {str(e)}")
            raise

    async def save_meeting_transcript(self, meeting_id: str, transcript: str, timestamp: str,
                                     summary: str = "", action_items: str = "", key_points: str = "",
                                     audio_start_time: float = None, audio_end_time: float = None, duration: float = None):
        """Save a transcript for a meeting"""
        try:
            async with self._get_connection() as conn:
                # No ON CONFLICT logic needed as transcripts table has SERIAL ID, duplicates allowed unless unique constraint
                await conn.execute("""
                    INSERT INTO transcript_segments (
                        meeting_id, transcript, timestamp, summary, action_items, key_points,
                        audio_start_time, audio_end_time, duration
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, meeting_id, transcript, timestamp, summary, action_items, key_points,
                      audio_start_time, audio_end_time, duration)
                return True
        except Exception as e:
            logger.error(f"Error saving transcript: {str(e)}")
            raise

    async def get_meeting(self, meeting_id: str):
        """Get a meeting by ID with all its transcripts"""
        try:
            async with self._get_connection() as conn:
                # Get meeting details
                meeting = await conn.fetchrow("""
                    SELECT id, title, created_at, updated_at, owner_id, workspace_id
                    FROM meetings
                    WHERE id = $1
                """, meeting_id)
                
                if not meeting:
                    return None
                
                # Get transcripts
                transcripts = await conn.fetch("""
                    SELECT transcript, timestamp, audio_start_time, audio_end_time, duration
                    FROM transcript_segments
                    WHERE meeting_id = $1
                """, meeting_id)

                return {
                    'id': meeting['id'],
                    'title': meeting['title'],
                    'created_at': meeting['created_at'].isoformat() if meeting['created_at'] else None,
                    'updated_at': meeting['updated_at'].isoformat() if meeting['updated_at'] else None,
                    'owner_id': meeting['owner_id'],
                    'workspace_id': meeting['workspace_id'],
                    'transcripts': [{
                        'id': meeting_id,
                        'text': t['transcript'],
                        'timestamp': t['timestamp'],
                        'audio_start_time': t['audio_start_time'],
                        'audio_end_time': t['audio_end_time'],
                        'duration': t['duration']
                    } for t in transcripts]
                }
        except Exception as e:
            logger.error(f"Error getting meeting: {str(e)}")
            raise

    async def get_full_transcript_text(self, meeting_id: str):
        """Get the full transcript text from full_transcripts table"""
        try:
            async with self._get_connection() as conn:
                row = await conn.fetchrow("""
                    SELECT transcript_text
                    FROM full_transcripts
                    WHERE meeting_id = $1
                """, meeting_id)
                return row['transcript_text'] if row else None
        except Exception as e:
            logger.error(f"Error getting full transcript: {str(e)}")
            return None

    async def update_meeting_title(self, meeting_id: str, new_title: str):
        """Update a meeting's title"""
        now = datetime.utcnow()
        async with self._get_connection() as conn:
            await conn.execute("""
                UPDATE meetings
                SET title = $1, updated_at = $2
                WHERE id = $3
            """, new_title, now, meeting_id)

    async def get_all_meetings(self):
        """Get all meetings with basic information"""
        async with self._get_connection() as conn:
            rows = await conn.fetch("""
                SELECT id, title, created_at, owner_id, workspace_id
                FROM meetings
                ORDER BY created_at DESC
            """)
            return [{
                'id': row['id'],
                'title': row['title'],
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                'owner_id': row['owner_id'],
                'workspace_id': row['workspace_id']
            } for row in rows]

    async def delete_meeting(self, meeting_id: str):
        """Delete a meeting and all its associated data"""
        if not meeting_id or not meeting_id.strip():
            raise ValueError("meeting_id cannot be empty")
            
        try:
            async with self._get_connection() as conn:
                # Postgres CASCADE delete handles dependent rows if configured in FKs.
                # Our migration script added ON DELETE CASCADE, so we just delete from meetings.
                result = await conn.execute("DELETE FROM meetings WHERE id = $1", meeting_id)
                
                if result == "DELETE 0":
                    logger.warning(f"Meeting {meeting_id} not found for deletion")
                    return False
                
                logger.info(f"Successfully deleted meeting {meeting_id} (and cascaded)")
                return True
                    
        except Exception as e:
            logger.error(f"Database connection error in delete_meeting: {str(e)}", exc_info=True)
            return False

    async def get_model_config(self):
        """Get the current model configuration"""
        async with self._get_connection() as conn:
            # Postgres column is likely lowercase 'whispermodel'
            row = await conn.fetchrow("SELECT provider, model, whisperModel FROM settings")
            if row:
                return {
                    "provider": row["provider"],
                    "model": row["model"],
                    "whisperModel": row["whispermodel"]
                }
            return None

    async def save_model_config(self, provider: str, model: str, whisperModel: str):
        """Save the model configuration"""
        try:
            async with self._get_connection() as conn:
                # Upsert settings (assuming id='1' is the singleton config)
                # Use unquoted whisperModel to match lowercase column
                await conn.execute("""
                    INSERT INTO settings (id, provider, model, whisperModel)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        model = EXCLUDED.model,
                        whisperModel = EXCLUDED.whisperModel
                """, '1', provider, model, whisperModel)
                
                logger.info(f"Successfully saved model configuration: {provider}/{model}")
        except Exception as e:
            logger.error(f"Failed to save model configuration: {str(e)}", exc_info=True)
            raise

    async def save_api_key(self, api_key: str, provider: str):
        """Save the API key"""
        provider_map = {
            "openai": "openaiapikey",
            "claude": "anthropicapikey",
            "groq": "groqapikey",
            "ollama": "ollamaapikey",
            "gemini": "geminiapikey"
        }
        if provider not in provider_map:
            raise ValueError(f"Invalid provider: {provider}")
        
        column_name = provider_map[provider]
        
        try:
            async with self._get_connection() as conn:
                # Check if row exists, if not insert default, then update
                # Or just Upsert with COALESCE for other fields? 
                # Simpler: Upsert a new row if not exists, then update specific column
                
                # Ensure row 1 exists
                await conn.execute("""
                    INSERT INTO settings (id, provider, model, whisperModel)
                    VALUES ('1', 'openai', 'gpt-4o', 'large-v3')
                    ON CONFLICT (id) DO NOTHING
                """)
                
                # Update specific key
                # Note: We can't use dynamic column name in execute params, must be f-string safely
                # column_name is from a safe whitelist above.
                await conn.execute(f"""
                    UPDATE settings SET "{column_name}" = $1 WHERE id = '1'
                """, api_key)
                
                logger.info(f"Successfully saved API key for provider: {provider}")
        except Exception as e:
            logger.error(f"Failed to save API key for provider {provider}: {str(e)}", exc_info=True)
            raise

    async def get_api_key(self, provider: str, user_email: Optional[str] = None):
        """Get the API key"""
        if user_email:
            user_key = await self.get_user_api_key(user_email, provider)
            if user_key:
                return user_key

        provider_map = {
            "openai": "openaiapikey",
            "claude": "anthropicapikey",
            "groq": "groqapikey",
            "ollama": "ollamaapikey",
            "gemini": "geminiapikey"
        }
        if provider not in provider_map:
            return ""
            
        column_name = provider_map[provider]
        async with self._get_connection() as conn:
            val = await conn.fetchval(f"SELECT \"{column_name}\" FROM settings WHERE id = '1'")
            return val if val else ""

    async def save_user_api_key(self, user_email: str, provider: str, api_key: str):
        """Save an encrypted API key for a specific user."""
        encrypted_key = encrypt_key(api_key)
        now = datetime.utcnow()
        async with self._get_connection() as conn:
            await conn.execute("""
                INSERT INTO user_api_keys (user_email, provider, api_key, updated_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT(user_email, provider) DO UPDATE SET
                    api_key = EXCLUDED.api_key,
                    updated_at = EXCLUDED.updated_at
            """, user_email, provider, encrypted_key, now)

    async def get_user_api_key(self, user_email: str, provider: str) -> Optional[str]:
        """Retrieve and decrypt an API key for a specific user."""
        async with self._get_connection() as conn:
            encrypted_key = await conn.fetchval(
                "SELECT api_key FROM user_api_keys WHERE user_email = $1 AND provider = $2 AND is_active = TRUE",
                user_email, provider
            )
            if encrypted_key:
                return decrypt_key(encrypted_key)
        return None

    async def get_user_api_keys(self, user_email: str) -> Dict[str, str]:
        """Retrieve all active API keys for a specific user (returns masked keys)."""
        keys = {}
        async with self._get_connection() as conn:
            rows = await conn.fetch(
                "SELECT provider, api_key FROM user_api_keys WHERE user_email = $1 AND is_active = TRUE",
                user_email
            )
            for row in rows:
                provider = row['provider']
                encrypted_key = row['api_key']
                decrypted = decrypt_key(encrypted_key)
                if decrypted and len(decrypted) > 8:
                    keys[provider] = f"{decrypted[:4]}...{decrypted[-4:]}"
                else:
                    keys[provider] = "****"
        return keys

    async def delete_user_api_key(self, user_email: str, provider: str):
        """Remove an API key for a specific user."""
        async with self._get_connection() as conn:
            await conn.execute(
                "DELETE FROM user_api_keys WHERE user_email = $1 AND provider = $2",
                user_email, provider
            )

    async def get_transcript_config(self):
        """Get the current transcript configuration"""
        async with self._get_connection() as conn:
            row = await conn.fetchrow("SELECT provider, model FROM transcript_settings")
            if row:
                return {"provider": row["provider"], "model": row["model"]}
            return {"provider": "localWhisper", "model": "large-v3"}

    async def save_transcript_config(self, provider: str, model: str):
        """Save the transcript settings"""
        try:
            async with self._get_connection() as conn:
                await conn.execute("""
                    INSERT INTO transcript_settings (id, provider, model)
                    VALUES ('1', $1, $2)
                    ON CONFLICT (id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        model = EXCLUDED.model
                """, provider, model)
                logger.info(f"Successfully saved transcript configuration: {provider}/{model}")
        except Exception as e:
            logger.error(f"Failed to save transcript configuration: {str(e)}", exc_info=True)
            raise

    async def save_transcript_api_key(self, api_key: str, provider: str):
        """Save the transcript API key"""
        provider_map = {
            "localWhisper": "whisperapikey",
            "deepgram": "deepgramapikey",
            "elevenLabs": "elevenlabsapikey",
            "groq": "groqapikey",
            "openai": "openaiapikey"
        }
        if provider not in provider_map:
            raise ValueError(f"Invalid provider: {provider}")
            
        column_name = provider_map[provider]
        
        try:
            async with self._get_connection() as conn:
                await conn.execute("INSERT INTO transcript_settings (id, provider, model) VALUES ('1', 'localWhisper', 'large-v3') ON CONFLICT (id) DO NOTHING")
                
                await conn.execute(f"""
                    UPDATE transcript_settings SET "{column_name}" = $1 WHERE id = '1'
                """, api_key)
                
                logger.info(f"Successfully saved transcript API key for provider: {provider}")
        except Exception as e:
            logger.error(f"Failed to save transcript API key for provider {provider}: {str(e)}", exc_info=True)
            raise

    async def get_transcript_api_key(self, provider: str, user_email: Optional[str] = None):
        """Get the transcript API key"""
        if user_email:
            user_key = await self.get_user_api_key(user_email, provider)
            if user_key:
                return user_key

        provider_map = {
            "localWhisper": "whisperapikey",
            "deepgram": "deepgramapikey",
            "elevenLabs": "elevenlabsapikey",
            "groq": "groqapikey",
            "openai": "openaiapikey"
        }
        if provider not in provider_map:
            raise ValueError(f"Invalid provider: {provider}")
            
        column_name = provider_map[provider]
        async with self._get_connection() as conn:
            val = await conn.fetchval(f"SELECT \"{column_name}\" FROM transcript_settings WHERE id = '1'")
            return val if val else ""

    async def search_transcripts(self, query: str):
        """Search through meeting transcripts for the given query"""
        if not query or query.strip() == "":
            return []
            
        search_query = f"%{query.lower()}%"
        
        try:
            async with self._get_connection() as conn:
                # 1. Search transcript_segments table
                rows = await conn.fetch("""
                    SELECT m.id, m.title, ts.transcript, ts.timestamp
                    FROM meetings m
                    JOIN transcript_segments ts ON m.id = ts.meeting_id
                    WHERE LOWER(ts.transcript) LIKE $1
                    ORDER BY m.created_at DESC
                """, search_query)
                
                # 2. Search full_transcripts table
                chunk_rows = await conn.fetch("""
                    SELECT m.id, m.title, ft.transcript_text
                    FROM meetings m
                    JOIN full_transcripts ft ON m.id = ft.meeting_id
                    WHERE LOWER(ft.transcript_text) LIKE $1
                    AND m.id NOT IN (SELECT DISTINCT meeting_id FROM transcript_segments WHERE LOWER(transcript) LIKE $2)
                    ORDER BY m.created_at DESC
                """, search_query, search_query)
                
                results = []
                
                # Helper to format results
                def format_match(row, text_col):
                    text = row[text_col]
                    lower_text = text.lower()
                    match_idx = lower_text.find(query.lower())
                    start = max(0, match_idx - 100)
                    end = min(len(text), match_idx + len(query) + 100)
                    context = text[start:end]
                    if start > 0: context = "..." + context
                    if end < len(text): context += "..."
                    
                    return {
                        'id': row['id'],
                        'title': row['title'],
                        'matchContext': context,
                        'timestamp': row.get('timestamp') or datetime.utcnow().isoformat()
                    }

                for row in rows:
                    results.append(format_match(row, 'transcript'))
                    
                for row in chunk_rows:
                    results.append(format_match(row, 'transcript_text'))
                    
                return results
                
        except Exception as e:
            logger.error(f"Error searching transcripts: {str(e)}")
            raise

    async def delete_api_key(self, provider: str):
        """Delete the API key"""
        provider_map = {
            "openai": "openaiapikey",
            "claude": "anthropicapikey",
            "groq": "groqapikey",
            "ollama": "ollamaapikey",
            "gemini": "geminiapikey"
        }
        if provider not in provider_map:
            raise ValueError(f"Invalid provider: {provider}")
            
        column_name = provider_map[provider]
        async with self._get_connection() as conn:
            await conn.execute(f"UPDATE settings SET \"{column_name}\" = NULL WHERE id = '1'")

    async def update_meeting_summary(self, meeting_id: str, summary: dict):
        """Update a meeting's summary"""
        now = datetime.utcnow()
        try:
            async with self._get_connection() as conn:
                async with conn.transaction():
                    # Check existence
                    exists = await conn.fetchval("SELECT id FROM meetings WHERE id = $1", meeting_id)
                    if not exists:
                        raise ValueError(f"Meeting with ID {meeting_id} not found")
                    
                    # Update summary_processes
                    await conn.execute("""
                        UPDATE summary_processes
                        SET result = $1, updated_at = $2
                        WHERE meeting_id = $3
                    """, json.dumps(summary), now, meeting_id)
                    
                    # Update meetings timestamp
                    await conn.execute("""
                        UPDATE meetings
                        SET updated_at = $1
                        WHERE id = $2
                    """, now, meeting_id)
                    
                    return True
        except Exception as e:
            logger.error(f"Error updating meeting summary: {str(e)}")
            raise
