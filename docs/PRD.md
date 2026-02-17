# PRD: PLC Knowledge Base — PDF Parser with LlamaIndex

**Version:** 1.0
**Date:** 2026-02-16
**Status:** Ready for Implementation

---

## 1. Overview

Build a RAG (Retrieval-Augmented Generation) system that ingests 25 PLC (Professional Learning Communities) education books from `data/pdfs/`, chunks and embeds them, stores vectors in a self-hosted Qdrant instance, and exposes a chat interface powered by OpenAI GPT-4 via LlamaIndex.

**Goal:** Answer questions about PLC theory, practice, and implementation grounded in actual book content — citations traceable to source pages, optionally augmented with live web search via Perplexity.

---

## 2. Problem Statement

25 PLC books represent hundreds of hours of reading. Educators and coaches need to:
- Surface specific guidance quickly (e.g., "how do singletons collaborate in a PLC?")
- Compare positions across authors
- Generate summaries per topic or per book
- Get citations with page references for professional use
- Optionally supplement book knowledge with current web sources

---

## 3. Users

- **Primary:** Educator/instructional coach (developer-adjacent, comfortable with terminal)
- **Secondary:** Future API consumers (web UI, integrations)

---

## 4. Functional Requirements

### FR-1: PDF Ingestion
- Parse all `.pdf` files in `data/pdfs/` using PyMuPDF (fitz)
- Extract: full text per page, page number, source filename, book title (derived from filename)
- Handle multi-column layouts, headers/footers, and table text gracefully
- Output: structured JSON per book saved to `data/processed/`
- Skip already-processed files unless `--force` flag is passed

### FR-2: Chunking
- Chunk text into ~512-token segments with 64-token overlap
- Preserve page number and source metadata on every chunk
- Use sentence-aware splitting (no mid-sentence cuts)

### FR-3: Embedding + Vector Store
- Embed chunks using OpenAI `text-embedding-3-large`
- Store in self-hosted Qdrant persisted to `data/qdrant/` (local) or remote Qdrant server
- Collection name: `plc_books`
- Support incremental updates (re-embed only new/changed files)

### FR-4: RAG Query Engine
- Use LlamaIndex `VectorStoreIndex` with Qdrant backend
- LLM: OpenAI GPT-4 (configurable model, default `gpt-4o`)
- Similarity top-k: 5 (configurable)
- Response synthesis: `tree_summarize` mode
- Always include source citations: `book_title | page N`

### FR-5: Web Search Augmentation (Conditional, MVP+)
- Optionally route queries to Perplexity API when book context is insufficient
- Triggered by: low similarity scores, explicit `--web` flag, or user command `!web <query>`
- Web results appended to context, clearly labeled as "Web Source"

### FR-6: CLI Interface (MVP)
- `python -m src.chat` launches interactive REPL
- Commands: `quit`, `clear`, `sources`, `help`, `!web <query>`
- Rich-formatted output
- Single-query mode: `python -m src.chat --query "..."`

### FR-7: Caching (Alpha+)
- Cache embeddings and query results in Redis
- TTL: 24h for query results, permanent for embeddings
- Cache key: SHA256 hash of query + model + top-k config

### FR-8: REST API (Alpha+)
- FastAPI server exposing `/query`, `/ingest`, `/health`
- Auth: API key header `X-API-Key`
- Async endpoints using `asyncio` + LlamaIndex async query engine

---

## 5. Non-Functional Requirements

- **Performance:** Full ingestion of 25 books < 5 minutes
- **Latency:** P95 query latency < 3s (excluding first-token)
- **Accuracy:** RAG answers must cite actual page content, not hallucinate
- **Scalability:** Architecture supports horizontal scale from MVP (single EC2) to Production (ECS/Fargate auto-scaling)

---

## 6. Infrastructure

### Compute

| Phase | Setup |
|-------|-------|
| MVP | Single EC2 |
| Alpha | Single EC2 |
| Beta | Multi-EC2 + Load Balancer |
| Production | Auto-scaling ECS/Fargate |

### Full Stack by Phase

| Component | MVP | Alpha | Beta | Production |
|-----------|-----|-------|------|------------|
| Compute | Single EC2 | Single EC2 | Multi-EC2 + LB | Auto-scaling ECS/Fargate |
| Vector Database | Qdrant (self-hosted) | Qdrant (self-hosted) | Qdrant (self-hosted, HA) | Qdrant (self-hosted, HA) |
| LLM | OpenAI GPT-4 (SDPA) | OpenAI GPT-4 (SDPA) | OpenAI GPT-4 (SDPA) | OpenAI GPT-4 (SDPA) |
| Web Search API | Perplexity (Conditional) | Perplexity | — | — |
| Caching | Redis | Redis Cluster | — | — |
| Database | PostgreSQL (RDS) | PostgreSQL (RDS Multi-AZ) | — | — |

---

## 7. Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| RAG Framework | LlamaIndex | Best-in-class RAG, Qdrant integration |
| LLM | OpenAI GPT-4 (SDPA) | Highest quality, structured output |
| Embeddings | OpenAI text-embedding-3-large | Best retrieval performance |
| Vector Store | Qdrant (self-hosted) | HA-ready, fast, open source |
| PDF Parser | PyMuPDF (fitz) | Fastest, best text extraction |
| Web Search | Perplexity API | Best semantic search quality |
| Cache | Redis | Session + query result caching |
| Database | PostgreSQL (RDS) | Metadata, usage logs, user sessions |
| API Server | FastAPI | Async, OpenAPI spec, auth middleware |
| CLI | Rich + prompt_toolkit | Beautiful REPL |
| Language | Python 3.11+ | Ecosystem compatibility |
| IaC | AWS CDK / Terraform | Reproducible infra |

---

## 8. Data

### Input PDFs (25 files, ~93MB total)

All PLC-themed books by Solution Tree:

| SKU | Title |
|-----|-------|
| bkf032 | Professional Learning Communities at Work: Best Practices |
| bkf273 | Building a PLC at Work: A Guide to the First Year |
| bkf653 | Yes We Can: General and Special Educators Collaborating in a PLC |
| bkf676 | How to Develop PLCs for Singletons and Small Schools |
| bkf683 | Time for Change: Four Essential Skills for Transformational Leadership |
| bkf705 | Concise Answers to FAQs about PLCs |
| bkf716 | Handbook for Collaborative Common Assessments |
| bkf770 | School Improvement for All |
| bkf793 | Transforming School Culture (2nd ed.) |
| bkf794 | Amplify Your Impact: Coaching Collaborative Teams |
| bkf840 | Make It Happen: Coaching with the Four Critical Questions |
| bkf891 | Behavior Solutions: Teaching Academic and Social Skills through RTI |
| bkf898 | Big Book of Tools for Collaborative Teams |
| bkf942 | Leading PLCs at Work Districtwide |
| bkf961 | Powerful Guiding Coalitions |
| bkf969 | 15-Day Challenge: Simplify and Energize Your PLC |
| bkg009 | Energize Your Teams: Coaching Collaborative Teams |
| bkg024 | Revisiting PLCs at Work (2nd ed.) |
| bkg039 | Singletons in a PLC at Work |
| bkg049 | Acceleration for All |
| bkg097 | Common Formative Assessment (2nd ed.) |
| bkg119 | All Means All: Essential Actions for Leveraging Yes We Can |
| bkg136 | Taking Action (2nd ed.): RTI at Work |
| bkg159 | The Way Forward: PLC at Work and the Bright Future of Education |
| bkg169 | Learning by Doing (4th ed.) |

### Output Structure
```
data/
  pdfs/           # input (read-only)
  processed/      # per-book JSON (text + metadata)
  qdrant/         # Qdrant local storage (dev only)
```

---

## 9. Success Metrics

- [ ] All 25 PDFs ingested without error
- [ ] Query "What are the four critical questions of a PLC?" returns accurate, cited answer
- [ ] Query "How should singleton teachers collaborate?" cites bkf676 or bkg039
- [ ] CLI starts in < 2 seconds after initial indexing
- [ ] P95 query latency < 3s on EC2

---

## 10. Milestones

| Phase | Deliverable |
|-------|-------------|
| MVP | PDF ingestion + Qdrant embedding + CLI chat + Perplexity fallback |
| Alpha | FastAPI server + Redis caching + EC2 deployment |
| Beta | Multi-EC2 + LB + Qdrant HA |
| Production | ECS/Fargate auto-scaling + RDS Multi-AZ |
