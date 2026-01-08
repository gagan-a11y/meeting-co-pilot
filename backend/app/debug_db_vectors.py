import asyncio
import os
import sys

# Add app directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

from db import DatabaseManager as Database
from vector_store import store_meeting_embeddings, get_collection_stats, search_context

async def inspect_and_test():
    db = Database(os.getenv("DATABASE_PATH", "data/meeting_minutes.db"))
    
    # 1. Get all meetings
    meetings = await db.get_all_meetings()
    print(f"Found {len(meetings)} meetings in DB.")
    
    if not meetings:
        print("No meetings found. Exiting.")
        return

    # 2. Pick the first meeting
    test_meeting_id = meetings[0]['id']
    print(f"\nInspecting Meeting: {test_meeting_id}")
    
    # 3. Get full details
    meeting_data = await db.get_meeting(test_meeting_id)
    print(f"Meeting Data Keys: {meeting_data.keys()}")
    
    transcripts = meeting_data.get("transcripts", [])
    print(f"Transcript Count: {len(transcripts)}")
    
    if transcripts:
        print(f"Sample Transcript: {transcripts[0]}")
    else:
        print("WARNING: No transcripts found for this meeting.")
        
        # Check raw transcripts table
        print("\nChecking 'transcripts' table directly...")
        import sqlite3
        with sqlite3.connect("data/meeting_minutes.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM transcripts WHERE meeting_id=?", (test_meeting_id,))
            count = cursor.fetchone()[0]
            print(f"Raw Transcripts Row Count: {count}")

    # 4. Try storing embeddings manually
    if transcripts:
        print(f"\nAttempting to store embeddings for {test_meeting_id}...")
        count = await store_meeting_embeddings(
            meeting_id=test_meeting_id,
            meeting_title=meeting_data.get("title", "Untitled"),
            meeting_date=meeting_data.get("created_at", ""),
            transcripts=transcripts
        )
        print(f"Stored {count} chunks.")
        
        # 5. Verify search
        print("\nVerifying Search...")
        stats = get_collection_stats()
        print(f"Collection Stats: {stats}")
        
        results = await search_context("meeting", allowed_meeting_ids=[test_meeting_id])
        print(f"Search Results: {len(results)}")

if __name__ == "__main__":
    asyncio.run(inspect_and_test())
