# PDF Parser Llama — PLC Knowledge Base

A RAG (Retrieval-Augmented Generation) system over 25 Professional Learning Communities (PLC) education books. Powered by LlamaIndex + OpenAI GPT-4 + Qdrant. Optional Perplexity web search fallback.

> **Branches:** `main` uses LLMSherpa (layout-aware) + GPT-4o Vision. See `test-pymupdf` for the PyMuPDF + `SimpleDirectoryReader` alternative.

---

## Stack

| Layer | Tool |
|-------|------|
| RAG Framework | LlamaIndex |
| LLM | OpenAI GPT-4 (`gpt-4o`) |
| Embeddings | OpenAI `text-embedding-3-large` |
| Vector Store | Qdrant (self-hosted) |
| PDF Parser | LLMSherpa (layout-aware) + GPT-4o Vision (reproducibles) |
| Cache | Redis |
| Database | PostgreSQL |
| Web Search | Perplexity API (optional) |
| API Server | FastAPI (Alpha+) |
| CLI | Rich + prompt_toolkit |
| Infra | AWS EC2 → ECS/Fargate |

---

## How Ingestion Works

Ingestion reads book metadata from `data/manifest.json`, then processes each PDF in two passes:

1. **Landscape/reproducible pages** — detected via PyMuPDF rotation metadata, rendered as images, and described with GPT-4o Vision into structured markdown nodes.
2. **All other pages** — parsed with `LayoutPDFReader` from [nlm-ingestor](https://github.com/nlmatics/nlm-ingestor) (the LLMSherpa service), which preserves heading hierarchy, tables, and lists as semantically distinct chunks.

**Metadata on every node:**

| Field | Description | Example |
|-------|-------------|---------|
| `book_title` | Full title from manifest | `Learning by Doing` |
| `authors` | Author list from manifest | `["DuFour", "DuFour"]` |
| `sku` | Solution Tree SKU | `bkf840` |
| `chapter` | Running chapter heading | `Chapter 3: Collaboration` |
| `section` | Running section heading | `The Four Questions` |
| `page_number` | 1-based page number | `42` |
| `chunk_type` | `body_text`, `title`, `list`, `table`, `reproducible`, `chapter_summary`, `callout` | `reproducible` |
| `reproducible_id` | ID extracted from GPT-4o description | `4.3` |

---

## Requirements

- Python 3.11+
- Docker + Docker Compose (for Qdrant, Redis, Postgres)
- [nlm-ingestor](https://github.com/nlmatics/nlm-ingestor) (LLMSherpa service) — run separately
- OpenAI API key
- Perplexity API key (optional, for web search fallback)

---

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Configure environment**

```bash
cp .env.example .env
# Required: add your OPENAI_API_KEY
```

**3. Start services**

```bash
docker-compose up -d
# Starts Qdrant (6333), Redis (6379), Postgres (5432)
```

**4. Start the LLMSherpa / nlm-ingestor service**

The LLMSherpa service is **not** included in `docker-compose.yml` — run it separately:

```bash
docker run -p 5010:5010 ghcr.io/nlmatics/nlm-ingestor:latest
```

Verify it's up:
```bash
curl http://localhost:5010/api/parseDocument
```

Set the URL in `.env` if you run it on a different host/port:
```env
LLMSHERPA_API_URL=http://localhost:5010/api/parseDocument?renderFormat=all
```

---

## Usage

### Step 1 — Ingest PDFs

Reads `data/manifest.json` → for each book, detects landscape pages (GPT-4o Vision) and runs LLMSherpa layout parsing → saves all nodes to `data/processed/nodes.json`.

```bash
python -m src.ingest
```

Options:
```
--pdf-dir PATH    Source PDF directory (default: data/pdfs)
--force           Re-process already-ingested files
--verbose         Show per-page progress
```

The summary table shows per-book node counts and reproducible counts.

### Step 2 — Embed

Embeds nodes into Qdrant using `text-embedding-3-large`.

```bash
python -m src.embed
```

Options:
```
--force    Wipe collection and re-embed from scratch
```

First run: ~3-5 min for 25 books (~93MB). Subsequent runs skip already-indexed SKUs.

### Step 3 — Chat

```bash
python -m src.chat
```

Single-query mode:

```bash
python -m src.chat --query "What are the four critical questions of a PLC?"
```

Queries are analyzed by GPT-4o to extract metadata filters (book title, author, chunk type, chapter) before hitting Qdrant. If the filtered search returns fewer than 3 results, it retries without filters.

### Chat Commands

| Command | Description |
|---------|-------------|
| `quit` / `exit` | Exit |
| `clear` | Clear screen |
| `sources` | Show full excerpts from last query |
| `!web <query>` | Force Perplexity web search |
| `help` | Show commands |

---

## Example Output

```
You: What are the four critical questions of a PLC?

 Answer
 ──────────────────────────────────────────────────────
 The four critical questions of a PLC are:
 1. What do we want students to learn?
 2. How will we know if they've learned it?
 3. How will we respond when students don't learn?
 4. How will we extend learning for those who are proficient?

 [bkf840] Make It Happen, page 12
 [bkg169] Learning by Doing (4th ed.), page 36
 [bkf705] Concise Answers to FAQs, page 8

 Sources
 ┌──────────────────────────────────┬────────┬──────┬───────┐
 │ Book                             │ SKU    │ Page │ Score │
 ├──────────────────────────────────┼────────┼──────┼───────┤
 │ Make It Happen                   │ bkf840 │ 12   │ 0.94  │
 │ Learning by Doing (4th ed.)      │ bkg169 │ 36   │ 0.91  │
 │ Concise Answers to FAQs about... │ bkf705 │ 8    │ 0.87  │
 └──────────────────────────────────┴────────┴──────┴───────┘
```

---

## API Server (Alpha)

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Service health (no auth) |
| `POST` | `/api/v1/query` | RAG query |
| `POST` | `/api/v1/ingest` | Trigger re-ingestion |

Auth: `X-API-Key` header (set `X-API-Key` in `.env`).

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is RTI at Work?", "use_web": false}'
```

---

## Project Structure

```
pdf-parser-llama/
├── CLAUDE.md              # One-shot implementation guide
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── data/
│   ├── manifest.json      # Book metadata (title, authors, SKU, filename)
│   ├── pdfs/              # Input PDFs (read-only)
│   ├── processed/         # nodes.json (generated by ingest)
│   └── qdrant/            # Local vector store (dev)
├── src/
│   ├── config.py          # pydantic-settings config (includes LLMSHERPA_API_URL)
│   ├── schema.py          # MetadataSchema TypedDict
│   ├── ingest.py          # LLMSherpa parsing + GPT-4o vision for reproducibles
│   ├── embed.py           # Qdrant embedding
│   ├── rag.py             # LlamaIndex query engine + dynamic filter extraction
│   ├── web_search.py      # Perplexity fallback
│   ├── cache.py           # Redis cache
│   ├── chat.py            # CLI REPL
│   └── api/
│       ├── main.py        # FastAPI app
│       ├── routes.py
│       └── middleware.py
├── tests/
│   ├── conftest.py
│   ├── test_ingest.py
│   ├── test_rag.py
│   └── test_api.py
└── docs/
    ├── PRD.md
    └── TECHSPEC.md
```

---

## Infrastructure

| Phase | Compute | Vector DB | Notes |
|-------|---------|-----------|-------|
| MVP | Single EC2 | Qdrant self-hosted | + Redis |
| Alpha | Single EC2 | Qdrant self-hosted | + Redis Cluster, RDS Multi-AZ |
| Beta | Multi-EC2 + LB | Qdrant HA | |
| Production | ECS/Fargate auto-scaling | Qdrant HA | |

---

## Troubleshooting

**`OPENAI_API_KEY is not set`**
```bash
echo "OPENAI_API_KEY=sk-..." >> .env
```

**`Collection not found`** — Run embed first:
```bash
python -m src.embed
```

**Re-index everything from scratch:**
```bash
python -m src.ingest --force
python -m src.embed --force
```

**Qdrant not running:**
```bash
docker-compose up -d qdrant
```

**LLMSherpa service not running** — ingest will fail at the layout parsing step:
```bash
docker run -p 5010:5010 ghcr.io/nlmatics/nlm-ingestor:latest
# Verify: curl http://localhost:5010/api/parseDocument
```

**Reduce embedding cost** — set smaller dimensions in `.env`:
```env
EMBED_DIMENSIONS=1536
```
(Must re-embed after changing dimensions.)

---

## PDFs

25 books from Solution Tree's PLC @ Work series. See `docs/PRD.md` for the full list.
