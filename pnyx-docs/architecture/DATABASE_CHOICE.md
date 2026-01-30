# Database Architecture Decision: Migrating to PostgreSQL

**Date:** 2025-01-21
**Status:** Approved / In Progress
**Previous State:** SQLite (Local file-based) + ChromaDB (Vector Store)
**Target State:** PostgreSQL (Relational + JSONB + Vector)

---

## 1. Executive Summary

We have decided to migrate the Meeting Co-Pilot backend from **SQLite** to **PostgreSQL**. While NoSQL solutions like MongoDB were considered for storing unstructured meeting summaries, PostgreSQL's hybrid nature (Relational + JSONB + Vectors) offers a superior unified architecture for our specific needs.

## 2. The Trade-off Analysis: SQL vs. NoSQL

We evaluated three primary database paradigms for the Meeting Co-Pilot:

### Option A: Relational (SQL) - **WINNER**
*   **Examples:** PostgreSQL, MySQL
*   **Strengths:** Strict schema enforcement, complex joins, data integrity (ACID), mature ecosystem.
*   **Weaknesses:** Historically rigid schemas, scaling writes horizontally is harder than NoSQL.

### Option B: Document Store (NoSQL)
*   **Examples:** MongoDB, Cassandra
*   **Strengths:** Flexible schemas (great for AI outputs), easy horizontal scaling.
*   **Weaknesses:** Weak relationship handling (no joins), "eventual consistency" models can complicate logic, typically requires a separate vector store.

### Option C: Embedded (Current State)
*   **Examples:** SQLite
*   **Strengths:** Zero config, extremely fast for read-heavy local apps.
*   **Weaknesses:** File locking (poor concurrency), no native vector search, difficult to deploy in stateless container environments.

## 3. Why PostgreSQL? (The "Super Weapon")

PostgreSQL was chosen because it allows us to consolidate three different systems into one, reducing operational complexity ("The Boring Stack").

### A. Unified Data & Vectors (`pgvector`)
*   **Problem:** Currently, we store metadata in SQLite and Embeddings in ChromaDB. This creates a "Dual-Write Problem". If a meeting is deleted in SQLite but the API call to ChromaDB fails, we have "ghost data" in our vector search.
*   **Solution:** With the `pgvector` extension, embeddings are stored in the same row as the transcript chunk. `DELETE FROM transcript_chunks WHERE meeting_id = 'xyz'` atomically removes both text and vectors.

### B. The "NoSQL" inside SQL (`JSONB`)
*   **Problem:** AI-generated summaries are unstructured and variable.
*   **Solution:** PostgreSQL's `JSONB` data type allows us to store arbitrary JSON blobs while still being able to index and query fields efficiently.
    *   *Query:* `SELECT * FROM summaries WHERE result->'action_items' @> '[{"priority": "high"}]'`

### C. Concurrency & Scaling
*   **Problem:** SQLite locks the entire database file during a write operation. As we add multiple users or background processing workers (summarization, ingestion), SQLite becomes a bottleneck.
*   **Solution:** PostgreSQL uses MVCC (Multiversion Concurrency Control), allowing high-throughput concurrent reads and writes.

## 4. Why Not MySQL?

MySQL is a robust and popular database, but it falls short for this specific AI-driven application in two critical areas:

### A. Vector Support (`pgvector`)
*   **MySQL:** Does not have a mature, native vector similarity search extension equivalent to `pgvector`. You would typically need to manage a separate vector database (like ChromaDB or Pinecone) alongside MySQL, maintaining the complexity of "Dual-Write" synchronization.
*   **PostgreSQL:** The `pgvector` extension allows us to store embeddings directly in the database table (`vector(1536)`). We can perform semantic searches ("Find transcripts semantically similar to this query") using standard SQL queries, keeping our architecture monolithic and simple.

### B. Unstructured Data Handling (`JSONB`)
*   **MySQL:** Has a `JSON` data type, but it is generally considered less flexible and performant for indexing complex, nested documents compared to Postgres.
*   **PostgreSQL:** Its `JSONB` (Binary JSON) implementation is widely regarded as the gold standard for NoSQL-like features in a relational database. It supports advanced indexing (GIN indices) that allow for extremely fast lookups on arbitrary keys within the JSON blob, which is essential for querying diverse AI-generated meeting summaries.

## 5. Implementation Plan

1.  **Dependencies:** Replace `aiosqlite` with `asyncpg` (high-performance async driver).
2.  **Infrastructure:** Add PostgreSQL service to `docker-compose.yml` with persistent volumes.
3.  **Migration Script:**
    *   Extract data from `meeting_minutes.db`.
    *   Transform schemas (e.g., SQLite `TEXT` JSON strings -> Postgres `JSONB`).
    *   Load into PostgreSQL.
4.  **Vector Migration:** (Phase 2) Move embeddings from ChromaDB to a `vector(1536)` column in Postgres.

## 5. Conclusion

By choosing PostgreSQL, we gain the flexibility of NoSQL (via `JSONB`) and the semantic search capabilities of a Vector DB (via `pgvector`) without losing the relational integrity required for User Management and RBAC. This drastically simplifies our infrastructure from `App + SQLite + ChromaDB` to just `App + Postgres`.
