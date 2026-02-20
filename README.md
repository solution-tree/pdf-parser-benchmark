# PDF Parser Llama — PLC Knowledge Base (PyMuPDF branch)

> **Branch:** `test-pymupdf` — PDF parsing via PyMuPDF + LlamaIndex `SimpleDirectoryReader`.
> Compare with `main` (LLMSherpa layout-aware parsing) to evaluate extraction quality.

A RAG (Retrieval-Augmented Generation) system over 25 Professional Learning Communities (PLC) education books. Powered by LlamaIndex + OpenAI GPT-4 + Qdrant. Optional Perplexity web search fallback.

---

## Stack

| Layer | Tool |
|-------|------|
| RAG Framework | LlamaIndex |
| LLM | OpenAI GPT-4 (`gpt-4o`) |
| Embeddings | OpenAI `text-embedding-3-large` |
| Vector Store | Qdrant (self-hosted) |
| PDF Parser | PyMuPDF via LlamaIndex `PyMuPDFReader` |
| Cache | Redis |
| Database | PostgreSQL |
| Web Search | Perplexity API (optional) |
| API Server | FastAPI (Alpha+) |
| CLI | Rich + prompt_toolkit |
| Infra | AWS EC2 → ECS/Fargate |

---

## How Ingestion Works

`SimpleDirectoryReader` + `PyMuPDFReader` produces **one Document per page**. A `SentenceSplitter` then chunks each page into overlapping text nodes via an `IngestionPipeline`. Repeated headers/footers appearing on > 40% of pages are stripped before chunking.

**Metadata on every node (auto-populated):**

| Field | Source | Example |
|-------|--------|---------|
| `sku` | Filename stem (first 6 chars) | `bkf032` |
| `book_title` | Filename slug → title-cased | `Professional Learning Communities At Work` |
| `source` | Filename stem | `bkf032_professional-learning...` |
| `page_label` | Set by `PyMuPDFReader` (1-based) | `12` |
| `file_name`, `file_path`, `file_size` | Set by `SimpleDirectoryReader` | — |

---

## Requirements

- Python 3.11+
- Docker + Docker Compose (for Qdrant, Redis, Postgres)
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

---

## Usage

### Step 1 — Ingest PDFs

Reads all PDFs in `data/pdfs/` → one Document per page via PyMuPDF → boilerplate stripped → chunked → saved to `data/processed/nodes.json`.

```bash
python -m src.ingest
```

Options:
```
--pdf-dir PATH    Source PDF directory (default: data/pdfs)
--force           Re-process already-ingested files
--verbose         Show per-page progress
```

### Step 2 — Embed

Embeds chunks into Qdrant using `text-embedding-3-large`.

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

Auth: `X-API-Key` header (set `API_KEY` in `.env`).

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
├── src/
│   ├── config.py          # pydantic-settings config
│   ├── ingest.py          # PyMuPDF parsing + SentenceSplitter chunking
│   ├── embed.py           # Qdrant embedding
│   ├── rag.py             # LlamaIndex query engine
│   ├── web_search.py      # Perplexity fallback
│   ├── cache.py           # Redis cache
│   ├── chat.py            # CLI REPL
│   └── api/
│       ├── main.py        # FastAPI app
│       ├── routes.py
│       └── middleware.py
├── data/
│   ├── pdfs/              # Input (read-only)
│   ├── processed/         # Parsed JSON (generated)
│   └── qdrant/            # Local vector store (dev)
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

**Reduce embedding cost** — set smaller dimensions in `.env`:
```env
EMBED_DIMENSIONS=1536
```
(Must re-embed after changing dimensions.)

---

## PDFs

25 books from Solution Tree's PLC @ Work series. See `docs/PRD.md` for the full list.
