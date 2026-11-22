-- Executed once when the PostgreSQL volume is first initialized.
-- pgvector backs the semantic-search requirement (15-databases) for Phase 2 embeddings (BGE).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy business-name matching for deduplication
CREATE EXTENSION IF NOT EXISTS pgcrypto;
