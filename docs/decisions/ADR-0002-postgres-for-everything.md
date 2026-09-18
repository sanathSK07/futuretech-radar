# ADR-0002: PostgreSQL (with pgvector and full-text search) as the only datastore

**Status:** Accepted · **Date:** 2026-09-17

## Context

The data model needs relational records, versioned assessments, vector similarity (dedup, semantic search), keyword search, and a technology relationship graph. The brief asks for graph visualisation in Phase 4. Free-tier hosting is required.

## Decision

PostgreSQL 16 on Neon with `pgvector` (HNSW) and native `tsvector` search. The relationship graph is an edge table queried with recursive CTEs.

## Alternatives considered

- **Postgres + Neo4j (or another graph DB):** natural fit for graph queries; rejected because expected edge counts are in the hundreds to low thousands, recursive CTEs handle 2–3 hops trivially at that scale, and a second datastore doubles operational and backup complexity.
- **Postgres + dedicated vector DB (Pinecone, Qdrant, Chroma):** rejected because pgvector at < 100k vectors is fast enough and keeps vectors transactional with their rows; SK's previous Chroma experience is not a reason to add a service.
- **Postgres + Elasticsearch/Meilisearch:** rejected; weighted `tsvector` plus RRF hybrid ranking is sufficient for MVP corpus size.

## Consequences

One backup, one migration tool, one connection string. Revisit if edges exceed ~10⁵, vectors exceed ~1M, or search relevance demands features Postgres FTS lacks (typo tolerance, faceting at scale). Neon's 0.5 GB free storage caps stored text; the design stores abstracts and extracted excerpts, not full papers.
