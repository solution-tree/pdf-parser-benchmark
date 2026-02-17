# Technical Specification: PLC Knowledge Base

**Version:** 1.0
**Date:** 2026-02-16

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                          │
│          CLI (prompt_toolkit + Rich)  │  FastAPI REST API    │
└─────────────────┬───────────────────────────────┬───────────┘
                  │                               │
┌─────────────────▼───────────────────────────────▼───────────┐
│                      RAG Layer (LlamaIndex)                   │
│   Query Engine → Retriever → Response Synthesizer            │
│   System Prompt: PLC coach persona, citation-required        │
└────────────┬──────────────────────┬─────────────────────────┘
             │                      │
┌────────────▼──────┐   ┌──────────▼──────────────────────────┐
│  Qdrant           │   │  OpenAI APIs                         │
│  (Vector Store)   │   │  - gpt-4o (LLM)                     │
│  Self-hosted      │   │  - text-embedding-3-large (embed)    │
│  COSINE distance  │   └─────────────────────────────────────┘
└───────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│                     Data Layer                               │
│   data/pdfs/       → PyMuPDF ingest                         │
│   data/processed/  → JSON chunks with metadata              │
│   data/qdrant/     → Local Qdrant storage (dev)             │
└─────────────────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│              Supporting Services                             │
│   Redis         → Query result cache (24h TTL)              │
│   PostgreSQL    → Usage logs, metadata, future user mgmt     │
│   Perplexity    → Web search fallback (conditional)          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow

### Ingestion Pipeline

```
data/pdfs/*.pdf
       │
       ▼
  PyMuPDF (fitz)
  - page.get_text("text") per page
  - boilerplate detection (line freq > 40%)
  - clean + join lines per page
       │
       ▼
  extract_metadata(path)
  - sku = filename[:6]
  - book_title from slug
  - source = filename stem
       │
       ▼
  LlamaIndex SentenceSplitter
  - chunk_size=512 tokens
  - chunk_overlap=64 tokens
  - metadata preserved per chunk
       │
       ▼
  data/processed/{sku}_chunks.json
  [{text, page_label, source, book_title, sku}, ...]
```

### Embedding Pipeline

```
data/processed/*_chunks.json
       │
       ▼
  Load as llama_index.Document objects
  (skip SKUs already in Qdrant unless --force)
       │
       ▼
  OpenAI text-embedding-3-large
  - dimensions: 3072 (default) or 1536
  - batch size: 100 chunks
  - retry: tenacity, max 3, exponential backoff
       │
       ▼
  QdrantVectorStore.add()
  - collection: plc_books
  - distance: COSINE
  - payload: {text, page_label, source, book_title, sku}
       │
       ▼
  data/qdrant/ (persisted local) or remote Qdrant
```

### Query Pipeline

```
User query string
       │
       ├── Redis cache check (SHA256 key)
       │   └── HIT: return cached QueryResult immediately
       │
       ▼ (MISS)
  OpenAI text-embedding-3-large
  (embed the query string)
       │
       ▼
  Qdrant similarity search
  - top_k=5 (configurable)
  - returns chunks + scores
       │
       ├── Check max(scores) < WEB_SEARCH_SCORE_THRESHOLD (0.65)
       │   └── YES: call Perplexity API, append [WEB] result to context
       │
       ▼
  LlamaIndex tree_summarize response synthesis
  - OpenAI gpt-4o with system prompt
  - Grounded in retrieved chunks
  - Citations required in response
       │
       ▼
  QueryResult {answer, sources: [SourceNode], used_web}
       │
       ├── Store in Redis cache (TTL=24h)
       ▼
  Render to CLI or return as JSON (API)
```

---

## 3. Qdrant Schema

### Collection: `plc_books`

```json
{
  "name": "plc_books",
  "vectors": {
    "size": 3072,
    "distance": "Cosine"
  },
  "payload_schema": {
    "text": "keyword",
    "page_label": "keyword",
    "source": "keyword",
    "book_title": "keyword",
    "sku": "keyword"
  }
}
```

Estimated vector count: 25 books × ~300 chunks avg = ~7,500 vectors.
Storage: ~7,500 × 3072 × 4 bytes = ~92MB raw vectors + ~10MB payload.

---

## 4. API Schema

### POST /api/v1/query

Request:
```json
{
  "query": "string",
  "use_web": false,
  "top_k": 5
}
```

Response:
```json
{
  "answer": "string",
  "used_web": false,
  "sources": [
    {
      "book_title": "string",
      "sku": "string",
      "page": "string",
      "excerpt": "string",
      "score": 0.94
    }
  ]
}
```

### GET /api/v1/health

Response:
```json
{
  "status": "ok",
  "qdrant": true,
  "redis": true,
  "collection_exists": true,
  "vector_count": 7432
}
```

---

## 5. Redis Cache Schema

Key: `plc_kb:{sha256(query + ":" + model + ":" + top_k)}`
Value: JSON-serialized `QueryResult`
TTL: 86400s (24h)

---

## 6. PostgreSQL Schema (Alpha)

```sql
-- Query log
CREATE TABLE query_log (
    id          BIGSERIAL PRIMARY KEY,
    query       TEXT NOT NULL,
    answer      TEXT,
    used_web    BOOLEAN DEFAULT FALSE,
    top_k       INT,
    latency_ms  INT,
    cached      BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Source log (linked to query_log)
CREATE TABLE source_log (
    id          BIGSERIAL PRIMARY KEY,
    query_id    BIGINT REFERENCES query_log(id),
    sku         VARCHAR(10),
    book_title  TEXT,
    page_label  VARCHAR(20),
    score       FLOAT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 7. Error Handling

| Error | Behavior |
|-------|----------|
| `OPENAI_API_KEY` not set | Print error, exit 1 before any API call |
| OpenAI rate limit (429) | Retry with exponential backoff, max 3 attempts |
| Qdrant unavailable | Raise `RuntimeError("Qdrant not available")`, exit 1 |
| Redis unavailable | Log warning, continue without cache |
| Perplexity API failure | Log warning, return RAG result without web augmentation |
| PDF parse failure | Log error for that file, continue with remaining PDFs |
| Collection not found | Print: "Run `python -m src.embed` first", exit 1 |

---

## 8. Configuration Reference

All settings in `src/config.py` via `pydantic-settings`. Source: `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | required | OpenAI API key |
| `LLM_MODEL` | `gpt-4o` | OpenAI model for generation |
| `EMBED_MODEL` | `text-embedding-3-large` | OpenAI embedding model |
| `EMBED_DIMENSIONS` | `3072` | Embedding vector dimensions |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `QDRANT_API_KEY` | `""` | Qdrant API key (production) |
| `QDRANT_COLLECTION` | `plc_books` | Vector collection name |
| `USE_LOCAL_QDRANT` | `true` | Use local file path vs remote |
| `CHUNK_SIZE` | `512` | Tokens per chunk |
| `CHUNK_OVERLAP` | `64` | Overlap tokens between chunks |
| `SIMILARITY_TOP_K` | `5` | Chunks retrieved per query |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `CACHE_TTL_SECONDS` | `86400` | Query cache TTL (24h) |
| `PERPLEXITY_API_KEY` | `""` | Perplexity API key (optional) |
| `WEB_SEARCH_SCORE_THRESHOLD` | `0.65` | Min score before web fallback |
| `API_KEY` | `""` | REST API auth key |
| `API_PORT` | `8000` | FastAPI server port |
| `DATABASE_URL` | postgres://... | PostgreSQL connection URL |

---

## 9. Deployment

### MVP / Alpha: Single EC2

```bash
# EC2 setup (Amazon Linux 2023)
sudo dnf install -y python3.11 docker docker-compose-plugin git
sudo systemctl start docker
sudo usermod -aG docker ec2-user

git clone <repo>
cd pdf-parser-llama
cp .env.example .env && vim .env  # set OPENAI_API_KEY

docker compose up -d  # start Qdrant + Redis + Postgres
pip install -r requirements.txt

python -m src.ingest
python -m src.embed
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

### Production: ECS/Fargate

- `Dockerfile` for app container
- Qdrant runs as a separate ECS service with EFS volume mount for persistence
- Redis via ElastiCache
- PostgreSQL via RDS Multi-AZ
- ALB in front of app containers
- Secrets via AWS Secrets Manager → environment injection

---

## 10. Security

- API key auth on all non-health endpoints (`X-API-Key` header)
- No user data stored in vectors (only book text)
- OpenAI key never logged
- `data/pdfs/` mounted read-only in Docker
- `.env` in `.gitignore` — never commit secrets
- Qdrant accessible only within VPC (no public port in production)

---

## 11. Monitoring (Production)

- CloudWatch metrics: ECS CPU/memory, ALB request count/latency
- Application metrics to emit:
  - `query_latency_ms` (histogram)
  - `cache_hit_rate` (gauge)
  - `qdrant_vector_count` (gauge)
  - `web_search_triggered` (counter)
- Alerts: P95 latency > 5s, error rate > 1%
