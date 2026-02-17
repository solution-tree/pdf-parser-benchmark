# CLAUDE.md — One-Shot Implementation Guide

You are implementing a **RAG system** over 25 PLC education PDFs using:
- **LlamaIndex** (RAG orchestration framework)
- **OpenAI GPT-4** (LLM, via `gpt-4o` model)
- **OpenAI text-embedding-3-large** (embeddings)
- **Qdrant** (self-hosted vector database)
- **Redis** (caching)
- **PostgreSQL** (metadata/logging)
- **Perplexity API** (optional web search fallback)

Read this file fully before writing any code. Everything you need is here.

---

## Project Goal

Parse 25 PDFs in `data/pdfs/`, embed them into Qdrant, and serve a CLI chat interface (MVP) and FastAPI server (Alpha) that answers questions about Professional Learning Communities with book citations.

---

## Exact File Structure to Create

```
pdf-parser-llama/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml          # Qdrant + Redis + Postgres + app
├── src/
│   ├── __init__.py
│   ├── config.py               # all config via pydantic-settings
│   ├── ingest.py               # PDF -> chunks -> data/processed/
│   ├── embed.py                # chunks -> Qdrant
│   ├── rag.py                  # LlamaIndex query engine
│   ├── web_search.py           # Perplexity API client
│   ├── cache.py                # Redis cache layer
│   ├── chat.py                 # CLI REPL entry point
│   └── api/
│       ├── __init__.py
│       ├── main.py             # FastAPI app (Alpha)
│       ├── routes.py           # /query, /ingest, /health
│       └── middleware.py       # API key auth
├── data/
│   ├── pdfs/                   # 25 PDFs (DO NOT TOUCH)
│   ├── processed/              # created by ingest.py
│   └── qdrant/                 # local Qdrant storage (dev only)
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_ingest.py
│   ├── test_rag.py
│   └── test_api.py
└── docs/
    ├── PRD.md
    └── TECHSPEC.md
```

---

## Implementation — Follow This Exact Order

### Step 1: requirements.txt

```
# Core RAG
llama-index>=0.12.0
llama-index-vector-stores-qdrant>=0.4.0
llama-index-embeddings-openai>=0.3.0
llama-index-llms-openai>=0.3.0

# Vector DB
qdrant-client>=1.9.0

# PDF
pymupdf>=1.24.0

# Cache
redis>=5.0.0

# Database
asyncpg>=0.29.0
sqlalchemy[asyncio]>=2.0.0

# API (Alpha)
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.0.0
pydantic-settings>=2.0.0

# CLI
rich>=13.0.0
prompt_toolkit>=3.0.0

# Utils
python-dotenv>=1.0.0
httpx>=0.27.0
tenacity>=8.0.0
```

### Step 2: src/config.py

Use `pydantic-settings` `BaseSettings`. All values read from `.env`. Provide a cached `get_config()` via `@lru_cache`.

```python
from pydantic_settings import BaseSettings
from pathlib import Path
from functools import lru_cache

class Config(BaseSettings):
    # Paths
    PDF_DIR: Path = Path("data/pdfs")
    PROCESSED_DIR: Path = Path("data/processed")
    QDRANT_LOCAL_PATH: Path = Path("data/qdrant")

    # OpenAI
    OPENAI_API_KEY: str
    LLM_MODEL: str = "gpt-4o"
    EMBED_MODEL: str = "text-embedding-3-large"
    EMBED_DIMENSIONS: int = 3072  # text-embedding-3-large native

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "plc_books"
    USE_LOCAL_QDRANT: bool = True  # False in production

    # RAG
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64
    SIMILARITY_TOP_K: int = 5

    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL_SECONDS: int = 86400  # 24h

    # Perplexity
    PERPLEXITY_API_KEY: str = ""
    PERPLEXITY_MODEL: str = "llama-3.1-sonar-large-128k-online"
    WEB_SEARCH_SCORE_THRESHOLD: float = 0.65  # fallback to web if best score < this

    # API
    API_KEY: str = ""
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/plc_kb"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def model_post_init(self, __context):
        self.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        if self.USE_LOCAL_QDRANT:
            self.QDRANT_LOCAL_PATH.mkdir(parents=True, exist_ok=True)

@lru_cache
def get_config() -> Config:
    return Config()
```

### Step 3: src/ingest.py

**Purpose:** Parse every PDF → nodes saved to `data/processed/`.

**Use the LlamaIndex-idiomatic pattern:** `SimpleDirectoryReader` + `PyMuPDFReader` + `IngestionPipeline`.

Do NOT use raw `fitz.open()` calls directly — LlamaIndex wraps PyMuPDF via `PyMuPDFReader` which gives one `Document` per page with metadata already populated. Custom metadata (SKU, book_title) is injected via the `file_metadata` callback on `SimpleDirectoryReader`.

**Deps:** `pip install llama-index-readers-file` (provides `PyMuPDFReader`, wraps `pymupdf`)

```python
from pathlib import Path
from collections import Counter
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PyMuPDFReader
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.ingestion import IngestionPipeline


def extract_book_meta(file_path: str) -> dict:
    """Inject SKU + book_title into every Document loaded from this file."""
    stem = Path(file_path).stem  # e.g. bkf032_professional-learning...
    sku = stem[:6]
    title_slug = stem[7:] if len(stem) > 7 else stem
    book_title = title_slug.replace("-", " ").replace("_", " ").title()
    return {"sku": sku, "book_title": book_title, "source": stem}


def strip_boilerplate(documents: list) -> list:
    """Remove repeated header/footer lines appearing on > 40% of pages."""
    all_lines = []
    for doc in documents:
        all_lines.extend(doc.text.splitlines())
    counts = Counter(l.strip() for l in all_lines if l.strip())
    boilerplate = {
        line for line, count in counts.items()
        if count > len(documents) * 0.4 and len(line) < 100
    }
    for doc in documents:
        clean = "\n".join(
            l for l in doc.text.splitlines()
            if l.strip() not in boilerplate
        )
        doc.text = clean
    return documents


def load_and_chunk(pdf_dir: Path, chunk_size: int = 512, chunk_overlap: int = 64) -> list:
    """
    LlamaIndex-idiomatic ingestion:
      SimpleDirectoryReader (PyMuPDFReader) -> one Document per page
      -> boilerplate strip
      -> IngestionPipeline (SentenceSplitter)
      -> nodes with full metadata inherited automatically
    """
    reader = SimpleDirectoryReader(
        input_dir=str(pdf_dir),
        required_exts=[".pdf"],
        file_extractor={".pdf": PyMuPDFReader()},  # one Document per page
        file_metadata=extract_book_meta,            # injects sku, book_title, source
    )
    documents = reader.load_data(show_progress=True)

    # PyMuPDFReader sets doc.metadata["source"] = 1-based page number string.
    # SimpleDirectoryReader also adds: file_name, file_path, file_size, dates.

    documents = strip_boilerplate(documents)

    pipeline = IngestionPipeline(
        transformations=[
            SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
        ]
    )
    nodes = pipeline.run(documents=documents, show_progress=True)
    # Each node.metadata inherits all doc metadata: sku, book_title, source,
    # page_label (set by PyMuPDFReader), file_name, etc.
    return nodes
```

**Metadata on every node (automatically populated, no manual wiring):**
- `sku` — e.g. `bkf032`
- `book_title` — e.g. `Professional Learning Communities At Work`
- `source` — filename stem
- `page_label` — 1-based page number (set by `PyMuPDFReader`)
- `file_name`, `file_path`, `file_size`, `creation_date` (set by `SimpleDirectoryReader`)

**CLI entry point:**
- argparse: `--pdf-dir`, `--force`, `--verbose`
- Rich progress bar (passed through via `show_progress=True`)
- Serialize nodes to `data/processed/nodes.json` using `node.to_dict()`
- Summary table at end: columns = [SKU, Title, Pages, Nodes, Status]

### Step 4: src/embed.py

**Purpose:** Load chunks → embed → upsert into Qdrant.

**Qdrant setup:**

```python
from qdrant_client import QdrantClient, models as qdrant_models
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core import VectorStoreIndex, StorageContext, Settings

def get_qdrant_client(config) -> QdrantClient:
    if config.USE_LOCAL_QDRANT:
        return QdrantClient(path=str(config.QDRANT_LOCAL_PATH))
    return QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY or None)

def build_index(config, force: bool = False) -> VectorStoreIndex:
    client = get_qdrant_client(config)

    if force:
        try:
            client.delete_collection(config.QDRANT_COLLECTION)
        except Exception:
            pass

    # Collection is auto-created by QdrantVectorStore
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=config.QDRANT_COLLECTION,
    )

    Settings.embed_model = OpenAIEmbedding(
        model=config.EMBED_MODEL,
        api_key=config.OPENAI_API_KEY,
        dimensions=config.EMBED_DIMENSIONS,
    )

    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Load all chunks from data/processed/
    documents = load_documents_from_processed(config.PROCESSED_DIR)

    return VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        show_progress=True,
    )
```

Load documents from `data/processed/*_chunks.json` → `Document` objects with full metadata.
Skip SKUs already present in Qdrant collection unless `--force`.

### Step 5: src/rag.py

**Purpose:** Load existing index, run queries, return structured results.

```python
from dataclasses import dataclass

@dataclass
class SourceNode:
    book_title: str
    sku: str
    page: str
    excerpt: str
    score: float

@dataclass
class QueryResult:
    answer: str
    sources: list[SourceNode]
    used_web: bool = False

SYSTEM_PROMPT = """You are a knowledgeable coach on Professional Learning Communities (PLCs) at Work.
Answer questions based ONLY on the provided book excerpts.
Always cite your sources using the format: [SKU] Book Title, page N.
If the information is not in the provided context, say so clearly.
Be specific and actionable in your responses."""
```

**Loading (never re-embed on query):**
```python
from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.llms.openai import OpenAI

def load_query_engine(config):
    client = get_qdrant_client(config)
    vector_store = QdrantVectorStore(client=client, collection_name=config.QDRANT_COLLECTION)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    Settings.llm = OpenAI(model=config.LLM_MODEL, api_key=config.OPENAI_API_KEY, system_prompt=SYSTEM_PROMPT)
    Settings.embed_model = OpenAIEmbedding(model=config.EMBED_MODEL, api_key=config.OPENAI_API_KEY)

    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)
    return index.as_query_engine(
        similarity_top_k=config.SIMILARITY_TOP_K,
        response_mode="tree_summarize",
    )
```

Parse response source nodes into `SourceNode` objects. Check if best score < `WEB_SEARCH_SCORE_THRESHOLD` and trigger web search if so.

### Step 6: src/web_search.py

**Purpose:** Perplexity API fallback when book context score is low.

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def perplexity_search(query: str, config) -> str:
    """Returns web search result as a string to append to RAG context."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            PERPLEXITY_API_URL,
            headers={"Authorization": f"Bearer {config.PERPLEXITY_API_KEY}"},
            json={
                "model": config.PERPLEXITY_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a PLC education expert. Answer concisely with sources."},
                    {"role": "user", "content": query}
                ],
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
```

### Step 7: src/cache.py

**Purpose:** Redis cache for query results (keyed by SHA256 of query + config hash).

```python
import hashlib, json
import redis.asyncio as redis

def make_cache_key(query: str, model: str, top_k: int) -> str:
    payload = f"{query}:{model}:{top_k}"
    return f"plc_kb:{hashlib.sha256(payload.encode()).hexdigest()}"

async def get_cached(r: redis.Redis, key: str) -> dict | None:
    val = await r.get(key)
    return json.loads(val) if val else None

async def set_cached(r: redis.Redis, key: str, result: dict, ttl: int = 86400):
    await r.setex(key, ttl, json.dumps(result))
```

### Step 8: src/chat.py

**Purpose:** CLI REPL using `prompt_toolkit` + `rich`.

On startup:
1. Check OpenAI API key is set
2. Load RAG query engine (show Rich spinner)
3. Connect to Redis (optional, warn if unavailable)

Commands:
- `quit` / `exit` / Ctrl+C → exit gracefully
- `clear` → clear screen
- `sources` → show full excerpts from last query in a Rich Panel
- `help` → show commands table
- `!web <query>` → force Perplexity search
- Any other input → RAG query

Output format:
- Answer: Rich `Panel` with title "Answer" and border style `bright_blue`
- Sources: Rich `Table` with columns: Book | SKU | Page | Score
- Web sources: labeled with `[WEB]` prefix in sources table

Single-shot mode: `python -m src.chat --query "..."` → print and exit with code 0.

### Step 9: src/api/ (Alpha)

**FastAPI server:**

`main.py`:
```python
from fastapi import FastAPI
from .routes import router
from .middleware import APIKeyMiddleware

app = FastAPI(title="PLC Knowledge Base API", version="1.0.0")
app.add_middleware(APIKeyMiddleware)
app.include_router(router, prefix="/api/v1")
```

`routes.py`:
- `GET /health` → `{"status": "ok", "qdrant": bool, "redis": bool}`
- `POST /query` → `{"query": str, "use_web": bool}` → `QueryResult`
- `POST /ingest` → trigger ingestion job (background task)

`middleware.py`:
- Check `X-API-Key` header against `config.API_KEY`
- Exempt `/health` from auth

### Step 10: docker-compose.yml

```yaml
version: "3.9"
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333", "6334:6334"]
    volumes: ["./data/qdrant:/qdrant/storage"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: plc_kb
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

volumes:
  pgdata:
```

### Step 11: tests/

**conftest.py:**
- Fixtures: `config` (test config with temp dirs), `mock_openai`, `sample_pdf_path`

**test_ingest.py:**
- `test_parse_pdf_extracts_pages`: parse one real PDF, assert pages > 0
- `test_boilerplate_removal`: inject repeated header, assert it's stripped
- `test_chunk_metadata_keys`: assert every chunk has `text`, `page_label`, `source`, `book_title`, `sku`
- `test_sku_extraction`: verify `bkf032` extracted from filename

**test_rag.py:**
- `test_query_returns_result`: mock OpenAI + Qdrant, assert `QueryResult` returned
- `test_sources_populated`: assert sources list non-empty
- `test_cache_hit`: assert second identical query hits cache, no OpenAI call

**test_api.py:**
- `test_health_endpoint`: GET /health returns 200
- `test_query_requires_auth`: POST /query without key returns 401
- `test_query_success`: POST /query with valid key returns answer

---

## Critical Implementation Notes

1. **Never re-embed on query.** `src/rag.py` loads from existing Qdrant collection. Only `src/embed.py` writes to Qdrant.

2. **Local vs remote Qdrant:**
   - `USE_LOCAL_QDRANT=True` (default dev): `QdrantClient(path="data/qdrant")`
   - `USE_LOCAL_QDRANT=False` (production): `QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)`

3. **text-embedding-3-large dimensions:** Default is 3072. You can reduce to 1536 or 256 for cost/speed by setting `dimensions=1536` in the OpenAI embedding call and Qdrant collection config. Keep consistent between embed and query.

4. **Qdrant collection creation:** `QdrantVectorStore` auto-creates the collection. If you need to set custom HNSW params for production, create the collection manually first:
   ```python
   client.create_collection(
       collection_name="plc_books",
       vectors_config=qdrant_models.VectorParams(size=3072, distance=qdrant_models.Distance.COSINE),
   )
   ```

5. **Perplexity fallback logic:** After getting RAG result, check `max(node.score for node in response.source_nodes)`. If < `WEB_SEARCH_SCORE_THRESHOLD` (0.65), call Perplexity and append result to answer with `[WEB]` label.

6. **Redis connection failure:** If Redis is unavailable, log a warning but continue without caching. Never crash on cache errors.

7. **OpenAI rate limits:** Use `tenacity` retry with exponential backoff on all OpenAI calls. Max 3 retries.

8. **Page metadata:** PyMuPDF pages are 0-indexed. Store as `page_num + 1`.

9. **Error on missing API key:**
   ```
   [ERROR] OPENAI_API_KEY is not set. Add it to your .env file.
   ```
   Exit with code 1 before making any API calls.

10. **Module entry points:** All scripts runnable as `python -m src.ingest`, `python -m src.embed`, `python -m src.chat`. Use `if __name__ == "__main__":` blocks.

---

## Environment Variables (.env.example)

```env
# Required
OPENAI_API_KEY=sk-...

# LLM/Embedding
LLM_MODEL=gpt-4o
EMBED_MODEL=text-embedding-3-large
EMBED_DIMENSIONS=3072

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
QDRANT_COLLECTION=plc_books
USE_LOCAL_QDRANT=true

# RAG
CHUNK_SIZE=512
CHUNK_OVERLAP=64
SIMILARITY_TOP_K=5

# Redis
REDIS_URL=redis://localhost:6379
CACHE_TTL_SECONDS=86400

# Perplexity (optional)
PERPLEXITY_API_KEY=
PERPLEXITY_MODEL=llama-3.1-sonar-large-128k-online
WEB_SEARCH_SCORE_THRESHOLD=0.65

# API (Alpha)
API_KEY=change-me-in-production
API_HOST=0.0.0.0
API_PORT=8000

# Database (Alpha)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/plc_kb
```

---

## User Workflow

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Set environment
cp .env.example .env
# Add OPENAI_API_KEY to .env

# 3. Start services (Qdrant + Redis + Postgres)
docker-compose up -d

# 4. Ingest PDFs
python -m src.ingest

# 5. Embed to Qdrant
python -m src.embed

# 6. Chat
python -m src.chat
```

---

## Validation Queries

Run these after implementation and verify cited, grounded answers:

1. `"What are the four critical questions of a PLC?"` → should cite bkf840, bkg169, or bkf705
2. `"How should singleton teachers collaborate?"` → should cite bkf676 and/or bkg039
3. `"What is the role of a guiding coalition?"` → should cite bkf961
4. `"How do collaborative teams use common formative assessments?"` → should cite bkf716 and/or bkg097
5. `"What is RTI at Work?"` → should cite bkf891 or bkg136

---

## Constraints

- Python 3.11+
- LLM: OpenAI GPT-4 only (no local models)
- Vector DB: Qdrant only (no ChromaDB, Pinecone, etc.)
- `data/pdfs/` is read-only — never modify PDFs
- All console output via `rich` (no bare `print()` in production code, only in tests/scripts)
- Cache failures must never crash the system
- All async code in `src/api/`, sync acceptable in `src/ingest.py` and `src/embed.py`
