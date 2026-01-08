import asyncio
from vector_store import get_collection_stats, search_context

async def check_vector_store():
    print("Checking Vector Store Stats...")
    stats = get_collection_stats()
    print(f"Stats: {stats}")
    
    # Try a broad search
    print("\nAttempting broad search 'meeting'...")
    results = await search_context(query="meeting", n_results=10)
    
    unique_ids = set()
    for r in results:
        unique_ids.add(r['meeting_id'])
    
    print(f"\nFound {len(results)} chunks from {len(unique_ids)} unique meetings:")
    for uid in unique_ids:
        print(f" - {uid}")



if __name__ == "__main__":
    asyncio.run(check_vector_store())
