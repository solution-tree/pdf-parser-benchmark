# PRD: PDF Parser Benchmark CLI

## 1. Purpose
Select the **best PDF parsing solution** for a **structure-dependent RAG ingestion pipeline** over **25 digital-text books**, with emphasis on:
- **Retrieval quality** chunkability, coherent structure, reading order.
- **Traceable citations** printed “book page number” and section path.

## 2. Goals
1. Provide a repeatable CLI workflow to benchmark multiple parsers on a representative subset of pages smoke test first, then confidence run.. A representative benchmark typically samples **50–100 pages** after an initial smoke test.
2. Produce a clear “winner” and diagnostics that explain *why* high-level + tech-readable..
3. Support a canonical internal document model JSON. and render standardized Markdown from it for scoring fair comparisons across parsers..
4. Track both:
   - **PDF page index** ground truth key.
   - **Printed page label** “book page number”, entered by humans in v1; detector planned for beta.
   - **Section path** entered during labeling; partial allowed.

## 3. Non-goals v1.
- Web UI for labeling or browsing diffs CLI only..
- OCR benchmarking all docs are digital text PDFs..
- Production ingestion pipeline this tool only benchmarks..

## 4. Users
- You + 1–4 reviewers creating ground truth and running benchmarks.

## 5. Parsers in scope initial top 5.
Benchmark the initial set:
- **LlamaParse**
- **Marker**
- **Azure Document Intelligence**
- **pdfplumber**
- **Surya**

> Note: Prefer local-only execution where possible; keep the architecture API-capable behind feature flags.

## 6. Benchmark phases
**Phase A — Smoke test v1 start.:** 15 pages total, spread across multiple books, intentionally including rotated pages + chart-heavy pages.  
**Phase B — Confidence run:** 50–100 pages total for higher confidence, after narrowing to the top 2–3 parsers.

## 7. Ground truth requirements
- Ground truth is the “perfect” extraction, created semi-automatically then **manually verified and corrected**.
- Stored **per page** as canonical JSON containing metadata + corrected content.
- During labeling v1.:
  - Human types **printed page label** book page number..
  - Human enters **section path** optional/partial allowed..

## 8. Scoring requirements
Composite score emphasizing structure for RAG:
- **Text Accuracy 40%.**: Edit similarity, BLEU, token F1
- **Structural Fidelity 60%.**: Tree edit distance, reading order accuracy, heading detection F1

Add **Traceability metrics** v1: low weight, always reported.:
- Printed page label: exact match + normalized match
- Section path: partial match scoring bonus metric.

## 9. Output artifacts per run.
Generate:
- Leaderboard JSON + CSV.
- Markdown diagnostic report high-level + technical detail.
- Charts overall + metric breakdown + complexity breakdown.
- Per-page diff bundles inspect failures.
- Combined raw results JSON

## 10. Winner selection rule
- Primary: highest overall weighted score
- If within **2%**, tie-break by:
  1. structure/reading-order/heading subscore traceability relevance.
  2. speed
  3. cost
  4. determinism variance if multiple trials enabled.

## 11. Risks & mitigations
- **Ground truth quality** is the #1 risk; invest in careful review and spot checks.
- API parsers may have **rate limits**, **cost**, and **nondeterminism**; mitigate via caching + optional multiple trials.
