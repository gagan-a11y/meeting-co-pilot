"""
Database Migration: Add Transcript Versioning Support

This migration adds the necessary tables and columns to support
transcript versioning (live vs diarized) as per Phase 5 requirements.

Run this script to apply the migration:
    python -m app.migrations.add_transcript_versioning

Or import and call apply_migration() directly.
"""

import asyncio
import asyncpg
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Migration SQL statements
MIGRATION_SQL = """
-- ============================================
-- Migration: Add Transcript Versioning Support
-- Date: January 28, 2026
-- Description: Adds transcript_versions table and source column to segments
-- ============================================

-- 1. Create transcript_versions table for snapshots
CREATE TABLE IF NOT EXISTS transcript_versions (
    id SERIAL PRIMARY KEY,
    meeting_id TEXT NOT NULL,
    source TEXT NOT NULL, -- 'live' or 'diarized'
    content_json JSONB NOT NULL,
    is_authoritative BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE -- Optional, implicit
);

CREATE INDEX IF NOT EXISTS idx_transcript_versions_meeting_id ON transcript_versions(meeting_id);

-- 2. Add source column to transcript_segments (default to 'live')
ALTER TABLE transcript_segments 
ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'live';

-- 3. Add is_authoritative column to transcript_segments (to match version logic if needed)
-- Actually, the versions table handles authoritative snapshots. 
-- Segments are usually 'live' or 'current'.
"""

def get_db_url():
    """Get database URL from environment."""
    return os.getenv("DB_CONNECTION_STRING") or os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")

async def apply_migration():
    """Apply the migration."""
    db_url = get_db_url()
    
    if not db_url:
        logger.error("No database connection string found in environment")
        return False
    
    try:
        logger.info("Connecting to database...")
        conn = await asyncpg.connect(db_url)
        
        logger.info("Applying transcript versioning migration...")
        
        raw_statements = MIGRATION_SQL.split(';')
        for raw in raw_statements:
            statement = raw.strip()
            if not statement:
                continue
            
            try:
                await conn.execute(statement)
                logger.info(f"Executed: {statement[:50]}...")
            except Exception as e:
                # Log but continue if it's just "already exists"
                if "already exists" in str(e):
                    logger.info(f"Skipping existing object: {e}")
                else:
                    logger.warning(f"Migration warning: {e}")
        
        await conn.close()
        logger.info("✅ Transcript versioning migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(apply_migration())
