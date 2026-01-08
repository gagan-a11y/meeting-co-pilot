"""
Vector Store Service - ChromaDB wrapper for cross-meeting context search.

This module handles:
- Storing transcript embeddings with meeting metadata
- Semantic search across all meetings
- Source citation retrieval
"""

import logging
import os
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ChromaDB setup (lazy loaded)
_chroma_client = None
_collection = None
_embedding_function = None
_init_lock = threading.Lock()  # Thread-safe initialization


def _get_embedding_function():
    """Get or create the embedding function."""
    global _embedding_function
    if _embedding_function is None:
        try:
            from chromadb.utils import embedding_functions
            
            # Try Sentence Transformers (local, free)
            _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            logger.info("✅ Using SentenceTransformer embeddings (all-MiniLM-L6-v2)")
        except Exception as e:
            logger.warning(f"⚠️ SentenceTransformer not available: {e}")
            # Fallback to default ChromaDB embeddings
            _embedding_function = None
    return _embedding_function


def _get_collection():
    """Get or create the ChromaDB collection (thread-safe)."""
    global _chroma_client, _collection
    
    # Fast path: already initialized
    if _collection is not None:
        return _collection
    
    # Slow path: needs initialization with lock
    with _init_lock:
        # Double-check: another thread might have initialized while we waited
        if _collection is not None:
            return _collection
        try:
            import chromadb
            from chromadb.config import Settings
            
            # Use persistent storage in data directory
            persist_dir = "/app/data/chromadb"
            os.makedirs(persist_dir, exist_ok=True)
            
            _chroma_client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(anonymized_telemetry=False)
            )
            
            # Get or create collection
            embedding_fn = _get_embedding_function()
            _collection = _chroma_client.get_or_create_collection(
                name="meeting_transcripts",
                embedding_function=embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
            
            logger.info(f"✅ ChromaDB initialized. Collection has {_collection.count()} documents.")
            
        except ImportError:
            logger.error("❌ ChromaDB not installed. Run: pip install chromadb")
            return None
        except Exception as e:
            logger.error(f"❌ ChromaDB initialization failed: {e}")
            return None
    
    return _collection


def chunk_transcript(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    """Split transcript into overlapping chunks for embedding.
    
    Args:
        text: Full transcript text
        chunk_size: Target size of each chunk in characters
        overlap: Overlap between chunks
    
    Returns:
        List of text chunks
    """
    if not text or len(text) < chunk_size:
        return [text] if text else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence endings
            for sep in ['. ', '! ', '? ', '\n']:
                last_sep = text.rfind(sep, start, end)
                if last_sep > start + chunk_size // 2:
                    end = last_sep + 1
                    break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap if end < len(text) else len(text)
    
    return chunks


async def store_meeting_embeddings(
    meeting_id: str,
    meeting_title: str,
    meeting_date: str,
    transcripts: List[Dict[str, Any]]
) -> int:
    """Store transcript embeddings for a meeting.
    
    Args:
        meeting_id: Unique meeting identifier
        meeting_title: Title of the meeting
        meeting_date: Date of the meeting (ISO format)
        transcripts: List of transcript entries with 'text', 'timestamp' keys
    
    Returns:
        Number of chunks stored
    """
    collection = _get_collection()
    if collection is None:
        logger.warning("⚠️ Vector store not available, skipping embedding storage")
        return 0
    
    # Combine all transcripts
    full_text = "\n".join([t.get('text', '') for t in transcripts if t.get('text')])
    
    if not full_text.strip():
        logger.info(f"ℹ️ No transcript text for meeting {meeting_id}")
        return 0
    
    # Chunk the transcript
    chunks = chunk_transcript(full_text)
    
    if not chunks:
        return 0
    
    # Prepare data for ChromaDB
    ids = [f"{meeting_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "meeting_id": meeting_id,
            "meeting_title": meeting_title,
            "meeting_date": meeting_date,
            "chunk_index": i,
            "total_chunks": len(chunks)
        }
        for i in range(len(chunks))
    ]
    
    try:
        # Delete existing embeddings for this meeting (upsert)
        existing = collection.get(where={"meeting_id": meeting_id})
        if existing and existing['ids']:
            collection.delete(ids=existing['ids'])
            logger.debug(f"🗑️ Deleted {len(existing['ids'])} existing chunks for meeting {meeting_id}")
        
        # Add new embeddings
        collection.add(
            ids=ids,
            documents=chunks,
            metadatas=metadatas
        )
        
        logger.info(f"✅ Stored {len(chunks)} chunks for meeting '{meeting_title}' ({meeting_id})")
        return len(chunks)
        
    except Exception as e:
        logger.error(f"❌ Failed to store embeddings: {e}")
        return 0


async def search_context(
    query: str,
    n_results: int = 5,
    allowed_meeting_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Search for relevant context across meetings.
    
    Args:
        query: Search query
        n_results: Number of results to return
        allowed_meeting_ids: Optional - list of meeting IDs to restrict search to
    
    Returns:
        List of results with text, meeting info, and distance score
    """
    collection = _get_collection()
    if collection is None:
        return []
    
    try:
        # Build where clause
        where = None
        if allowed_meeting_ids:
            if len(allowed_meeting_ids) == 1:
                where = {"meeting_id": allowed_meeting_ids[0]}
            else:
                where = {"meeting_id": {"$in": allowed_meeting_ids}}
        
        logger.info(f"Querying vector store with filter: {where}")
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        formatted = []
        if results and results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                distance = results['distances'][0][i] if results['distances'] else 1.0
                
                formatted.append({
                    "text": doc,
                    "meeting_id": metadata.get("meeting_id", ""),
                    "meeting_title": metadata.get("meeting_title", "Unknown"),
                    "meeting_date": metadata.get("meeting_date", ""),
                    "similarity": 1 - distance,  # Convert distance to similarity
                    "chunk_index": metadata.get("chunk_index", 0)
                })
        
        logger.debug(f"🔍 Found {len(formatted)} results for query: '{query[:50]}...'")
        return formatted
        
    except Exception as e:
        logger.error(f"❌ Search failed: {e}")
        return []


def get_collection_stats() -> Dict[str, Any]:
    """Get statistics about the vector store."""
    collection = _get_collection()
    if collection is None:
        return {"status": "unavailable", "count": 0}
    
    try:
        return {
            "status": "available",
            "count": collection.count(),
            "name": collection.name
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
