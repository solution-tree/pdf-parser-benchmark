# Action Items & Improvements Roadmap

Implementation order based on Awesome-RAG research (see `docs/AWESOME_RAG_ANALYSIS.md`). Each improvement should be measured against RAGAS baseline before and after.

---

## 🚀 Priority Enhancements (Ordered by Implementation Sequence)

### 1. RAGAS Evaluation Baseline
**Status:** Planned
**Priority:** CRITICAL — Do this first
**Effort:** ~2-3 hours

**Problem:**
Without a baseline evaluation, you cannot measure whether hierarchical chunking, HyDE, or other improvements actually work. You could add features that hurt performance without knowing.

**Solution:**
Implement RAGAS evaluation framework on your 5 validation queries. RAGAS measures:
- **Faithfulness** (0–1): Does the answer contradict the retrieved context? Avoid hallucinations.
- **Answer Relevancy** (0–1): Does the answer address the question?
- **Context Precision** (0–1): Are the retrieved chunks actually useful?
- **Context Recall** (0–1): Did retrieval find all relevant chunks?

```python
# tests/eval_rag.py
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall

eval_dataset = {
    "question": [
        "What are the four critical questions of a PLC?",
        "How should singleton teachers collaborate?",
        # ... 5 validation queries
    ],
    "answer": [...],  # your system's answers
    "contexts": [...],  # retrieved source excerpts
    "ground_truth": [...],  # expected citations
}

result = evaluate(
    eval_dataset,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall]
)
print(f"Faithfulness: {result['faithfulness'].score:.3f}")
```

**Files to change:**
- `tests/eval_rag.py` (new)
- `src/config.py` — add RAGAS model config if needed

**Test:**
```bash
python tests/eval_rag.py
# Output: baseline metrics (Faithfulness, Answer Relevancy, Context Precision, Context Recall)
```

**Why it's critical:**
All subsequent improvements (hierarchical chunking, HyDE, re-ranking) should be measured against this baseline. You'll know exactly if they help or hurt.

---

### 2. Hybrid Search — BM25 + Vector
**Status:** Planned
**Priority:** High
**Effort:** ~1 hour

**Problem:**
Pure vector search captures semantic similarity but misses exact domain terminology:
- "guiding coalition" (the book's formal term) might not match user query "leadership group"
- "RTI at Work" (branded framework) might be paraphrased in the query
- "common formative assessment" (domain-specific jargon) benefits from keyword matching

Currently: single vector retrieval → possible misses on domain terminology precision.

**Solution:**
Combine vector search + BM25 (keyword search). Create a `BM25Retriever` alongside your existing vector retriever, then fuse results with `QueryFusionRetriever`.

```python
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers import QueryFusionRetriever

bm25_retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=5)
vector_retriever = index.as_retriever(similarity_top_k=5)

hybrid_retriever = QueryFusionRetriever(
    [vector_retriever, bm25_retriever],
    similarity_top_k=5,
    mode="reciprocal_rerank",  # RRF fusion: rerank by combined score
)
```

**Why for teacher coaching:**
Teachers ask in coach language; books use formal terminology. BM25 catches the formal terms. Hybrid search returns richer context from both semantic + exact matches.

**Files to change:**
- `src/rag.py` — add `BM25Retriever` + `QueryFusionRetriever`
- `src/embed.py` — pass nodes to BM25 during indexing (no re-embedding)

**Test:**
```bash
python -m src.chat --query "How do we build guiding coalition support?"
# Expect: retrieved chunks include both semantic matches and exact "guiding coalition" terms
```

**Measure with RAGAS before and after.** Context precision should improve.

---

### 3. Cross-Encoder Re-ranking
**Status:** Planned
**Priority:** High
**Effort:** ~30 min

**Problem:**
Current pipeline: retrieve top-k=5 via vector similarity → send all 5 to GPT-4o. Vector similarity is a proxy for relevance. Sometimes it's wrong:
- Query "How do we handle resistance?" retrieves "resistance to change" (high vector similarity) but context is less relevant than "stakeholder buy-in strategies."

**Solution:**
After retrieval, use a cross-encoder (models like BGE, Cohere) to jointly score (query, chunk) pairs and rerank. Select top-3 most relevant to pass to GPT-4o.

```python
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

reranker = FlagEmbeddingReranker(
    model="BAAI/bge-reranker-base",
    top_n=3  # keep top-3 after reranking
)

engine = index.as_query_engine(
    similarity_top_k=10,  # retrieve 10, rerank to 3
    node_postprocessors=[reranker],
)
```

**Why for teacher coaching:**
Cross-encoders catch nuanced relevance better than vector similarity alone. Example: "How do we build trust?" — a cross-encoder will score (query, "collaborative decision-making context") higher because the full meaning is more relevant, even if raw vector similarity is lower.

**Effort:** No re-indexing. Runs locally (no API cost).

**Files to change:**
- `src/rag.py` only — add `FlagEmbeddingReranker` postprocessor

**Test:**
```bash
python -m src.chat --query "What is the role of a guiding coalition?"
# Expect: cleaner, more precise top-3 results
```

**Measure with RAGAS. Context precision should improve significantly.**

---

### 4. Fix Sub-Question Decomposition Trigger
**Status:** Planned
**Priority:** Medium
**Effort:** ~15 min

**Problem:**
Current trigger set: `{"compare", "difference", "both", "vs", "and", "contrast", "versus"}`

This is too broad. Fires on simple queries like:
- "What are PLCs and how do they work?" (contains "and") → decomposition triggered unnecessarily

Decomposition adds latency + LLM calls for 95% of queries that don't need it.

**Solution:**
Narrow the trigger to only genuine comparison/synthesis keywords. **Measure decomposition performance against RAGAS baseline first, then consider upgrading to an LLM classifier if needed** (e.g., routing complex multi-part questions more accurately):

```python
DECOMPOSITION_TRIGGERS = {"compare", "versus", "vs", "contrast", "difference"}
# Removed: "and", "both" (too common in simple questions)
```

**Files to change:**
- `src/rag.py` — update `DECOMPOSITION_TRIGGERS` set

**Test:**
```bash
python -m src.chat --query "What are PLCs and how do they work?"
# Expect: fast path, single retrieval (no decomposition)
python -m src.chat --query "Compare guiding coalitions and teacher teams"
# Expect: decomposition triggered, two sub-questions, synthesis answer
```

**Upgrade Path:** If keyword-based triggers still miss true decomposition opportunities after RAGAS evaluation, implement a lightweight LLM classifier to route multi-part queries intelligently.

---

### 5. Hierarchical Chunking with AutoMergingRetriever
**Status:** Planned
**Priority:** High
**Effort:** ~2 hours

**Problem:**
Current ingestion uses flat `SentenceSplitter` (512-token chunks). This means:
- Small chunks lose surrounding context
- Comparison questions need multiple retrieval hops to gather both concepts
- Parent/child relationships between chunks are lost

**Solution:**
Replace with `HierarchicalNodeParser` + `AutoMergingRetriever`:
- Parse PDFs into 3-level hierarchy: 2048 → 512 → 128 token chunks
- Store all nodes (parent + leaf) in docstore
- Only embed leaf nodes in vector store (cost savings)
- At query time: retrieve leaf nodes, auto-merge siblings up to parents for broader context

```python
from llama_index.core.node_parser import HierarchicalNodeParser
from llama_index.core.retrievers import AutoMergingRetriever

parser = HierarchicalNodeParser.from_defaults(
    chunk_sizes=[2048, 512, 128],
    chunk_overlap=128,  # 20% overlap for better context
)

nodes = parser.get_nodes_from_documents(documents)
# Store all nodes, embed only leaf nodes
```

**Files to change:**
- `src/config.py` — add `CHUNK_SIZES: list[int] = [2048, 512, 128]`
- `src/ingest.py` — swap `SentenceSplitter` for `HierarchicalNodeParser`
- `src/embed.py` — separate leaf/parent nodes in storage context
- `src/rag.py` — use `AutoMergingRetriever` + `RetrieverQueryEngine`

**Test:**
```bash
python -m src.ingest --force
python -m src.embed --force
python -m src.chat --query "What are the four critical questions of a PLC?"
# Verify answer includes richer context from merged parent chunks
```

**Measure with RAGAS. Context recall should improve significantly for comparison queries.**

---

### 6. HyDE (Hypothetical Document Embeddings)
**Status:** Planned
**Priority:** Medium
**Effort:** ~1 hour

**Problem:**
Coach language ("get buy-in," "build trust") ≠ book language ("guiding coalition," "stakeholder engagement"). Query embedding trained on coach language, but book chunks use formal academic language. Vocabulary gap → poor retrieval.

**Solution:**
Use LLM to generate a hypothetical answer to the query (in book/formal vocabulary), then embed and search with that instead of the user's original query.

```python
from llama_index.query_transforms.hyde import HyDEQueryTransform

hyde_transform = HyDEQueryTransform(include_original=True)
# Chains: LLM generates hypothetical answer → embeds both original + hypothetical → retrieves from both

engine = index.as_query_engine(
    query_transforms=[hyde_transform],
)
```

**Why for teacher coaching:**
Bridges the vocabulary gap. Example:
- User: "How do we get buy-in from resistant people?"
- HyDE generates: "Build trust through collaborative decision-making, inclusive leadership, and stakeholder engagement..."
- Embedding searches for this formal language → matches book content better

**Files to change:**
- `src/rag.py` — add `HyDEQueryTransform`

**Test:**
```bash
python -m src.chat --query "How do we get buy-in from resistant teachers?"
# Expect: matches "guiding coalition" and "stakeholder engagement" from books
```

**Measure with RAGAS. Answer relevancy should improve for coaching-specific questions.**

---

### 7. LangFuse Observability
**Status:** Planned
**Priority:** Medium
**Effort:** ~1 hour

**Problem:**
You have no visibility into system performance:
- Which queries are slow?
- How often does web search trigger?
- What's the actual cost per query?
- What's the failure pattern?

**Solution:**
Integrate LangFuse, an open-source LLM observability platform. One-line callback registration in LlamaIndex gives you traces, latency metrics, token usage, and failure analysis.

```python
from llama_index.callbacks.langfuse import langfuse_callback_handler

Settings.callback_manager = CallbackManager([langfuse_callback_handler()])
```

**Why for production:**
Before deploying to teachers, you need dashboards showing query latency, token costs, and error patterns. LangFuse is self-hostable and integrates cleanly with LlamaIndex.

**Files to change:**
- `src/config.py` — add LangFuse credentials
- `src/rag.py` — register callback
- Deployment docs — add LangFuse Docker service

**Test:**
```bash
# Deploy LangFuse (Docker)
# Run a few queries
# Check LangFuse dashboard for traces, latency, tokens
```

---

### 8. Semantic Caching for Query Normalization
**Status:** Planned
**Priority:** Low
**Effort:** ~1.5 hours

**Problem:**
Current Redis cache uses SHA256 of exact query string. Users don't ask identical questions twice:
- "What are the four critical questions?" ≠ "What are the 4 critical questions?"
- "What is a PLC?" ≠ "Tell me about PLCs"

Same intent → different cache keys → cache misses → unnecessary OpenAI calls.

**Solution:**
Implement semantic caching: use query embeddings to find cached results with >0.95 similarity.

```python
# Instead of:
cache_key = f"plc_kb:{hashlib.sha256(query.encode()).hexdigest()}"

# Use embedding similarity to find similar cached queries
query_vec = embed_model.get_text_embedding(query)
# Search cached query embeddings for cosine_similarity > 0.95
# If found, return cached result (same intent)
```

**Trade-off:** Each cache lookup costs one embedding call (~$0.0001), but saves LLM calls on rephrased questions. Only worthwhile if cache hit rate > 15%.

**Why deprioritized:**
Coaching questions are diverse (unlikely high hit rate). Implement only if Redis exact-match analysis shows >15% of misses are due to rephrasing (not diverse intent).

---

## 🔄 Completed

- ✅ PDF ingestion with metadata extraction (SKU, book title)
- ✅ Boilerplate stripping (headers/footers on 40%+ of pages)
- ✅ OpenAI embeddings → Qdrant vector DB
- ✅ CLI chat with Redis caching
- ✅ FastAPI server with API key auth
- ✅ Web search fallback (Perplexity) for low-confidence answers

---

## 🎯 Future Ideas (Lower Priority)

- **Incremental indexing** — When adding new PDFs in the future, avoid re-embedding the entire corpus. Implement a delta-based ingestion pipeline that tracks which PDFs have been processed (via metadata in Postgres), embeds only new PDFs, and upserts their nodes into Qdrant. This scales the system from 25 fixed books to a growing knowledge base without re-indexing costs.

- **Semantic chunking** — use LLM to identify natural chunk boundaries (vs token count)
- **Metadata filtering** — refine queries by SKU or date range before retrieval
- **Cost optimization** — reduce embedding dimension from 3072 to 1536 or 256
- **Async ingestion** — background PDF processing via job queue
- **Chat history** — maintain multi-turn conversation context
- **Logging to Postgres** — persist query history for analytics
