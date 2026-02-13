# AGENTS.md (Codex CLI)

This repo builds a CLI app to benchmark PDF parsers for a RAG ingestion pipeline.

## Goal
Implement a reproducible benchmark pipeline:
PDFs + sampled pages -> parser outputs -> canonical JSON -> standardized Markdown -> evaluation -> report artifacts.

## Non-goals (v1)
- No web UI
- No OCR focus (all PDFs are digital text)
- No production ingestion pipeline (benchmark only)

## Key conventions
- Ground truth is page-level canonical JSON under ground_truth/<document_id>/<pdf_page_number>.json
- Runs go under runs/<run_id>/... and must be reproducible.
- Always cache raw outputs (native parser outputs) so re-scoring does not require re-parsing.

## Required CLI commands (v1)
- bench init
- bench sample --phase smoke|confidence
- bench gt create
- bench gt edit
- bench run --phase <phase> --parsers <list>
- bench eval --phase <phase>
- bench report --phase <phase>

## Scoring defaults
- overall = 0.40 * text_accuracy + 0.60 * structural_fidelity
- deterministic metrics only in v1
- report traceability metrics (page label + section path) separately (low weight)

## Implementation guidance
- Prefer small, testable modules.
- Use a plugin adapter pattern for parsers.
- Make config-driven behavior via benchmark.yaml.
- Provide a mock mode or tiny fixture so tests can run without proprietary PDFs.
- Ensure commands create the expected folder structure and artifacts.

## Acceptance proof
When asked to deliver v1, you should:
- install dependencies
- run the CLI smoke test in mock/fixture mode
- show generated artifacts in runs/<run_id>/report/

## Dataset & sampling
- PDFs live under `data/pdfs/<document_id>.pdf` (v1 local)
- Dataset manifest: `data/manifest.json` (must include `pdf_page_count` so page existence is well-defined)
- Sample sets:
  - `data/samples/smoke_test.json`
  - `data/samples/confidence_run.json`
  Each is a list of `{document_id, pdf_page_number}`.

## Ground truth workflow
- Ground truth is page-level canonical JSON under `ground_truth/<document_id>/<pdf_page_number>.json`
- Labelers enter `book_page_label` (printed page number) and `section_path` (optional/partial).
- Provide `bench gt validate` to run sanity checks (duplicates, monotonicity, offset stability) after labeling.
