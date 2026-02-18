# Awesome-RAG Analysis: Findings for PLC Knowledge Base

**Reviewed:** [github.com/Danielskry/Awesome-RAG](https://github.com/Danielskry/Awesome-RAG)
**Date:** 2026-02-18
**Applicability:** Professional Learning Communities (PLCs) coaching Q&A system over 25 fixed-corpus PLC education books

---

## Use Case Framing

Your system serves **teachers and school leaders asking situational coaching questions** about their work — not SKU lookups or reference searches. Examples:
- "How do we get buy-in from resistant teachers?"
- "What's the role of a guiding coalition?"
- "How should singleton teachers collaborate?"

The expectation: **grounded, cited answers** with page numbers from the 25 PLC books. The corpus is **fixed** (not real-time, not growing) and **domain-specific** (educational leadership terminology).

This framing significantly changes which Awesome-RAG techniques are high-ROI vs. low-ROI.

---

## Current System State ✅

Implemented and working:
- PDF ingestion via PyMuPDF with metadata extraction (SKU, book title, page number)
- Flat SentenceSplitter chunking (512 tokens, 64-token overlap)
- OpenAI `text-embedding-3-large` → Qdrant vector store
- LlamaIndex query engine with top-k=5 retrieval and tree_summarize response mode
- Redis caching (exact string SHA256)
- Perplexity web search fallback for low-confidence answers
- FastAPI server with API key auth
- CLI REPL with Rich formatting

---

## Technique Catalog

### Chunking Strategies

| Technique | Verdict | Rationale |
|-----------|---------|-----------|
| **Fixed-Size Chunking** (current) | ✅ Acceptable | Simple, predictable. 512 tokens works for PLC book prose. Sentence-aware splitting mitigates mid-sentence cuts. |
| **Semantic Chunking** | ⏳ Low priority | Expensive (requires embedding per potential boundary). Fixed corpus means one-time cost, but not critical until evaluation shows retrieval quality issues. |
| **Hierarchical Chunking** | 🔥 High priority | **PLANNED.** Significantly improves context window for comparison queries ("How do guiding coalitions and teacher teams differ?"). Enables small chunks for precision, large chunks for context. |
| **Document-Based Chunking** | 🟡 Medium priority | **PLANNED.** While books are continuous prose, a hybrid approach can leverage natural document structure: detect chapter/section headers + maintain page boundaries as chunk anchor points. Combines fixed-size chunking (512 tokens) with document-aware boundaries to preserve semantic units. Implement after hierarchical chunking baseline to measure precision gains. |
| **Agentic Chunking** | ❌ Overkill | Too expensive and complex for a 25-book corpus. No ongoing ingestion to amortize cost. |

**Chunking best practice:** Your overlap (64 tokens, ~12%) is solid. After hierarchical chunking, increase to 15-20% to maintain context across 3-level hierarchy.

---

### Retrieval Techniques

| Technique | Verdict | Rationale |
|-----------|---------|-----------|
| **Vector Search** (current) | ✅ Core | Working as expected. Semantic matching on coach language. |
| **Hybrid Search (BM25 + Vector)** | 🔥 High priority | **NEW.** Domain-specific terminology ("guiding coalition," "RTI at Work," "common formative assessment") benefits from exact phrase matching. Teachers may use colloquial language, books use formal language — BM25 catches the formal terms. NOT about SKU lookup, about terminology precision. |
| **Hypothetical Document Embeddings (HyDE)** | 🟡 Medium priority | **NEW.** When user asks "get buy-in from resistant people," embeddings search for semantic similarity. HyDE generates a hypothetical answer first ("You can build trust by involving them in decisions..."), then searches with that embedding — bridges coaching language ↔ book academic language. Effective for domain vocabulary gaps. |
| **Small-to-Big Retrieval** | ⏳ Covered by hierarchical chunking | Once hierarchical chunking is implemented, retrieve small leaf chunks, auto-merge up to parents for context. Same effect without separate orchestration. |
| **Contextual Retrieval (Anthropic)** | ⏳ Medium effort, medium ROI | Each chunk gets a 20-40 token LLM-generated context prefix before embedding ("This section describes the role of..."). High ingestion cost (1 LLM call per chunk = 7,500 calls), single-time cost. Moderate quality gain. Worth revisiting after evaluation baseline. |
| **Adaptive Retrieval** | ❌ Not applicable | "Dynamically decide how much to retrieve during generation." Your queries are predictable (coaching Q&A), top-k=5 is sufficient. No evidence of need. |
| **Query Expansion / Reformulation** | 🟡 Low-medium priority | Expand user query ("PLC" → also search "Professional Learning Community," "collaborative team") before retrieval. Simple to implement, helps recall. Include if evaluation shows false negatives. |

---

### Ranking & Filtering

| Technique | Verdict | Rationale |
|-----------|---------|-----------|
| **Cross-Encoder Re-ranking** | 🔥 High priority | **NEW.** After retrieval of top-k=10, use BGE cross-encoder or Cohere reranker to reorder and select top-3. Jointly scores (query, chunk) pairs — catches cases where vector similarity is misleading. Significant precision gain, no re-indexing. |
| **Metadata Filtering** | 🟡 Medium priority | If user mentions a specific book ("What does bkf032 say..."), pre-filter Qdrant query to that SKU. Precision improvement and latency savings. Implement after RAGAS baseline. |
| **Diversity Constraints** | ❌ Not needed | You have 5 sources per query max. Diversity not a concern. |

---

### Response & Caching

| Technique | Verdict | Rationale |
|-----------|---------|-----------|
| **Tree Summarize** (current) | ✅ Solid | Good for extracting structured answers from retrieved chunks. Working well. |
| **Semantic Caching** | ⏳ Low priority — conditional | **PLANNED BUT DEPRIORITIZED.** Embedding-based cache lookup costs ~$0.0001 per query. Only worthwhile if cache hit rate is >20%. Your coaching questions are diverse (unlikely high hit rate). Implement only if Redis cache hit rate analysis shows >15% actual misses due to rephrasing. |
| **Prompt Caching (Claude API feature)** | ❌ Out of scope | You use OpenAI GPT-4o. Claude's prompt caching irrelevant. |

---

### Prompting & Orchestration

| Technique | Verdict | Rationale |
|-----------|---------|-----------|
| **Sub-Question Decomposition** | 🟡 Conditional priority | **PLANNED BUT NEEDS FIX.** Current trigger set `{"compare", "difference", "both", "vs", "and", "contrast"}` fires on simple queries like "What are PLCs and how do they work?" (contains "and"). **Narrow to only `{"compare", "versus", "vs", "contrast", "difference"}`** to avoid false positives. Start with keyword triggers (no LLM cost). Measure performance against RAGAS baseline first, then consider upgrading to an LLM classifier if keyword triggers are insufficient for complex multi-part questions. Only 5–10% of queries warrant decomposition. |
| **Chain of Thought (CoT)** | ✅ Built-in | Your system prompt requires "specific and actionable responses" — implicit CoT. System prompt is good. |
| **Few-Shot Prompting** | ⏳ Not critical | Your domain is well-defined (PLCs, books). Current system prompt sufficient. |
| **ReAct (Reason + Act)** | ❌ Out of scope | Tool calling / agentic workflows. Your system doesn't use tools beyond web search. |

---

### Observability & Evaluation

| Technique | Verdict | Rationale |
|-----------|---------|-----------|
| **RAGAS Evaluation Framework** | 🔥 CRITICAL — implement first | **NEW, MUST-HAVE.** Before implementing hierarchical chunking, HyDE, or re-ranking, establish a baseline. RAGAS evaluates: **faithfulness** (does answer contradict retrieved context?), **answer relevancy** (does it address the question?), **context precision** (are retrieved chunks useful?), **context recall** (did retrieval find the right chunks?). Your 5 validation queries are a perfect test set. Implement `tests/eval_rag.py` to run RAGAS. Measure every change against this baseline. |
| **LangFuse Observability** | 🟡 Medium priority | **NEW.** Open-source LLM monitoring. Integrates with LlamaIndex via 1-line callback. Gives you query latency, token usage, web search trigger rate, failure patterns. Critical for production. Implement after evaluation baseline. |
| **Weights & Biases** | ⏳ Optional | Heavier than LangFuse. Skip unless you're doing extensive experimentation. |

---

### Databases & Infrastructure

| Technique | Verdict | Rationale |
|-----------|---------|-----------|
| **Qdrant Vector DB** (current) | ✅ Good choice | Open-source, self-hosted, local dev friendly. No issues. |
| **PostgreSQL + pgvector** | ❌ Not needed | Qdrant is purpose-built for similarity search. pgvector adds complexity. Stick with Qdrant. |
| **Redis caching** (current) | ✅ Solid | Simple cache layer. Works well for exact-match queries. Semantic caching is low-priority given diverse coaching questions. |

---

## Prioritized Recommendations

Ordered by implementation sequence (each builds on prior):

---

### 1. RAGAS Evaluation Baseline — `[CRITICAL]` `[~2-3 hours]`

**What it is:**
Framework to measure RAG pipeline quality on: faithfulness, answer relevancy, context precision, context recall. Run on your 5 validation queries.

**Why for teachers/coaches:**
You have no way to know if hierarchical chunking or HyDE actually improves answers. RAGAS quantifies improvement. Example metrics:
- Faithfulness 0.92 (answers don't hallucinate beyond retrieved chunks)
- Answer relevancy 0.88 (answers address the question)
- Context precision 0.81 (top-k retrieval are relevant)

**Effort:** ~2–3 hours
**Files affected:** `tests/eval_rag.py` (new), `src/config.py` (add RAGAS_MODELS config)

**Do this first.** All other improvements should be measured against this baseline.

---

### 2. Hybrid Search — BM25 + Vector — `[HIGH]` `[~1 hour]`

**What it is:**
Combine vector similarity search + keyword (BM25) search. Retrieve top-5 from both, rerank/fuse results. Catches exact domain terminology.

**Why for teachers/coaches:**
Domain terms like "guiding coalition," "RTI at Work," "common formative assessment" benefit from exact phrase matching. Vector search alone can miss these when users use synonyms. BM25 ensures terminology precision.

**Example:** User asks "How do we build leadership capacity?" Vector search finds "guiding coalition" (semantic). BM25 finds "leadership" (exact). Fusion returns both — fuller context.

**Effort:** ~1 hour
**Files affected:** `src/rag.py` (add `BM25Retriever` + `QueryFusionRetriever`), `src/embed.py` (pass nodes to BM25)

**Implement after RAGAS baseline so you can measure the quality gain.**

---

### 3. Cross-Encoder Re-ranking — `[HIGH]` `[~30 min]`

**What it is:**
After retrieving top-k=10, use a cross-encoder (BGE, Cohere) to jointly score (query, chunk) pairs and select top-3 to pass to GPT-4o.

**Why for teachers/coaches:**
Vector similarity can be misleading. Cross-encoders catch nuanced relevance. Example: query "How do we handle resistance?" might vector-retrieve "resistance to change" (semantic). Cross-encoder scores (query, chunk) together and might re-rank a chunk about "stakeholder buy-in" higher because the full context is more relevant.

**Effort:** ~30 min
**Files affected:** `src/rag.py` only (add `FlagEmbeddingReranker` postprocessor)

**No re-indexing. Works with existing Qdrant collection. Immediate quality improvement.**

---

### 4. Fix Sub-Question Decomposition Trigger — `[MEDIUM]` `[~15 min]`

**What it is:**
Narrow the decomposition keyword set. Current: `{"compare", "difference", "both", "vs", "and", "contrast", "versus"}` — too broad. New: `{"compare", "versus", "vs", "contrast", "difference"}` only.

**Why for teachers/coaches:**
Current trigger fires on "What are PLCs and how do they work?" (contains "and"). This simple query doesn't need decomposition — it needs a single coherent answer. Decomposition adds latency and LLM calls for 95% of queries that don't need it.

**Effort:** ~15 min
**Files affected:** `src/rag.py` (update `DECOMPOSITION_TRIGGERS` set)

---

### 5. Hierarchical Chunking + AutoMergingRetriever — `[HIGH]` `[~2 hours]`

**What it is:**
3-level hierarchy: 2048 → 512 → 128 token chunks. Store all levels in docstore, embed only leaf nodes (cost savings), auto-merge siblings at query time for context.

**Why for teachers/coaches:**
Comparison queries benefit enormously: "How do guiding coalitions and teacher teams differ?" Leaf chunks isolate each concept. Auto-merger returns both + context from parents. Rich, contextualized answers.

**Effort:** ~2 hours
**Files affected:** `src/config.py` (add `CHUNK_SIZES`), `src/ingest.py` (swap `SentenceSplitter` for `HierarchicalNodeParser`), `src/embed.py`, `src/rag.py`

**Implement after RAGAS baseline + hybrid search. Measure against baseline to confirm improvement.**

---

### 6. HyDE (Hypothetical Document Embeddings) — `[MEDIUM]` `[~1 hour]`

**What it is:**
LLM generates a hypothetical answer to the user query, then embeds that (instead of the query itself) for retrieval.

**Why for teachers/coaches:**
Coach language ("get buy-in," "build trust") ≠ book language ("guiding coalition," "stakeholder engagement"). Hypothetical answer bridges the gap — it's written in book vocabulary, so its embedding matches book content better.

**Example:**
- User: "How do we get buy-in from resistant teachers?"
- HyDE generates: "Build trust through collaborative decision-making and inclusive leadership. Empower teachers to shape initiatives..."
- Embedding searches for this (formal language) instead of "get buy-in" (colloquial) — better matches.

**Effort:** ~1 hour
**Files affected:** `src/rag.py` (add `HyDEQueryTransform` postprocessor)

**Implement after hierarchical chunking. Measure against baseline.**

---

### 7. LangFuse Observability — `[MEDIUM]` `[~1 hour]`

**What it is:**
Open-source LLM observability. Integrates with LlamaIndex via callback handler. Tracks query latency, token usage, web search triggers, failures.

**Why for teachers/coaches:**
Before going to production, you need visibility: Which queries are slow? How often does web search trigger? What's the actual cost per query? LangFuse gives you dashboards and trace inspection.

**Effort:** ~1 hour (self-hosted) or 10 min (cloud)
**Files affected:** `src/config.py` (add LangFuse credentials), `src/rag.py` (register callback), deployment docs

**Implement after evaluation baseline. Critical for production readiness.**

---

## What to Skip (Low ROI for This Use Case)

| Technique | Why skip |
|-----------|----------|
| **Multimodal RAG** (images, audio) | PDFs are text-only. No image tables/diagrams that need vision. |
| **VideoRAG** | Source material is books, not videos. |
| **Graph RAG** (Microsoft) | Overkill for a 25-book corpus. Designed for large heterogeneous knowledge bases. Your domain is well-defined, flat hierarchy. |
| **RAFT Fine-tuning** | Fine-tuning an LLM for RAG. Cost-prohibitive and overkill. Your base GPT-4o is strong enough for coaching questions. |
| **Semantic Chunking** | Expensive (1 embedding per potential boundary). Flat corpus, batch processing — fixed cost of ~$50, but gains are marginal until vector search quality is actually a problem. Defer until evaluation shows need. |
| **Agentic RAG** | LLM decides retrieval strategy dynamically. Overkill for predictable coaching Q&A. Your fixed top-k=5 retrieval is sufficient. |

---

## Implementation Sequence Summary

```
1. RAGAS Evaluation Baseline ─────────────────────────┐
                                                       │
2. Hybrid Search (BM25 + Vector) ────────────┐        │
                                             ├─ Measure against baseline
3. Cross-Encoder Re-ranking ─────────────────┤
                                             │
4. Fix Sub-Question Decomposition Trigger ───┤
                                             │
5. Hierarchical Chunking + AutoMerging ──────┘

6. HyDE Query Transform ──────────────────────── Measure

7. LangFuse Observability ────────────────── Before production
```

---

## Key Metrics to Track (RAGAS + LangFuse)

| Metric | Target | Notes |
|--------|--------|-------|
| Faithfulness (RAGAS) | >0.90 | Answers don't hallucinate beyond context |
| Answer Relevancy (RAGAS) | >0.85 | Answers address the question |
| Context Precision (RAGAS) | >0.80 | Top-k retrieval are relevant |
| Cache Hit Rate | >10% | Exact-match questions (unlikely, diverse coaching) |
| Web Search Trigger Rate | <5% | Low-confidence answers fall back to Perplexity |
| P95 Latency | <3s | Query + retrieval + generation |
| Token Cost per Query | <$0.10 | Monitor embedding + LLM token usage |

---

## Sources

- [Awesome-RAG Repository](https://github.com/Danielskry/Awesome-RAG) — Full technique catalog, framework guide, evaluation tools
- RAGAS Framework: https://docs.ragas.io
- LangFuse: https://langfuse.com
- LlamaIndex Docs: https://docs.llamaindex.ai
- BGE Re-ranker: https://github.com/FlagOpen/FlagEmbedding#reranker
