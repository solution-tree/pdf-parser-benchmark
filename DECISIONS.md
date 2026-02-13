# DECISIONS: PDF Parser Benchmark CLI

This file records the key product/tech decisions so Codex (and humans) don't have to guess.

## Scope
- CLI-only (no web UI) for v1
- Python-first implementation (package + CLI entrypoint)

## Dataset
- Corpus: 25 owned-IP books (digital-text PDFs)
- v1 Smoke test: 15 pages total, spread across multiple books
- v1 Confidence run: 50–100 pages after narrowing to top 2–3 parsers
- Rotated pages are included and must be handled by parsers (no auto-rotate preprocessing baseline)

## Output representation
- Canonical internal format: document model JSON per PDF page
- Standardized Markdown is rendered from canonical JSON for scoring + human review
- Ground truth is page-level canonical JSON (one file per page)

## Traceability / citations
- Track both:
  - pdf_page_number (primary key)
  - book_page_label (printed page number) — entered by humans in v1
  - section_path — entered during labeling (optional/partial allowed)
- Printed page label detection (top+bottom) planned for beta (auto-detect + confirm)

## Parsers (initial benchmark set)
- LlamaParse (API-capable)
- Marker (local)
- Azure Document Intelligence (API-capable)
- pdfplumber (local)
- Surya (local)

## Scoring
- Composite weighting: 40% text accuracy, 60% structural fidelity
- v1 uses deterministic metrics only (no LLM-as-judge)
- Codex can assist with ground-truth editing/diff summaries but does not influence scores in v1
- Winner rule:
  - highest overall weighted score
  - within 2%: tie-break by structure subscore, then speed, then cost, then determinism

## Deliverables per run
- Leaderboard CSV + JSON
- Markdown diagnostic report (high-level + tech-readable)
- Charts (PNG)
- Per-page diff bundles
- combined_results.json

## Dataset files
- PDFs: `data/pdfs/<document_id>.pdf`
- Manifest: `data/manifest.json` (must include `pdf_page_count`)
- Sample sets: `data/samples/smoke_test.json`, `data/samples/confidence_run.json`

## Ground truth validation
- After labeling, run `bench gt validate` to flag likely page-label typos/outliers (duplicates, monotonicity, offset stability).
