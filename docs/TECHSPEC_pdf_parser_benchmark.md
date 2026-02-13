# Tech Spec: PDF Parser Benchmark CLI Python-first.

## 1. System overview
A CLI tool that runs:

1. **Ingest / sample** pages Phase A: 15 pages; Phase B: 50–100 pages.  
2. **Ground truth creation** seed parse → manual correction.  
3. **Parser runs** parser → native output → canonical doc model.  
4. **Normalization** canonical doc model → standardized Markdown.  
5. **Evaluation** metrics + composite scoring + traceability metrics.  
6. **Comparison report** leaderboard + charts + diagnostics.

## 2. Repository layout suggested.
```
pdf_benchmark/
  benchmark.yaml
  data/
    pdfs/                     # local PDFs v1.
    manifest.json             # list of docs + metadata
    samples/
      smoke_test.json         # selected pages for Phase A
      confidence_run.json     # selected pages for Phase B
  ground_truth/               # page-level JSON
  runs/
    <run_id>/
      raw_outputs/
        <parser_name>/...     # cached native outputs
      canonical/
        <parser_name>/...     # canonical page JSON outputs
      markdown/
        <parser_name>/...     # standardized Markdown per page
      eval/
        <parser_name>_results.json
      report/
        comparison_report.md
        *.png
        combined_results.json
  src/
    parsers/
    canonical/
    normalize/
    eval/
    report/
  cli.py
```


## 2.1. Dataset manifest & sample sets
### Manifest
The CLI generates/maintains `data/manifest.json` as the source of truth for the dataset.

Minimum fields per document:
```json
{
  "document_id": "book_01",
  "pdf_path": "data/pdfs/book_01.pdf",
  "pdf_page_count": 312,
  "title": "Optional human title",
  "edition": "Optional"
}
```

### Sample sets
A sample set is a list of page references stored as JSON:
- `data/samples/smoke_test.json`
- `data/samples/confidence_run.json`

Format:
```json
[
  {"document_id": "book_01", "pdf_page_number": 12},
  {"document_id": "book_03", "pdf_page_number": 88}
]
```

**Page existence rule:** `pdf_page_number` must be in `1..pdf_page_count` from the manifest.

## 3. Canonical data model v1.
Per **PDF page**:

```json
{
  "document_id": "book_01",
  "pdf_page_number": 12,
  "book_page_label": "57",
  "section_path": ["Unit 2", "Lesson 4", "Activity"],
  "page_attributes": {
    "layout_complexity": "moderate",
    "content_type": "figure_heavy",
    "has_rotation": true
  },
  "elements": [
    { "type": "heading", "level": 2, "text": "Lesson 4: ..." },
    { "type": "paragraph", "text": "..." },
    { "type": "list_item", "text": "..." },
    {
      "type": "table",
      "cells": [[{"text":"..."}, {"text":"..."}]],
      "caption": "Table 4.1 ..."
    },
    { "type": "figure", "caption": "Figure 2.3 ...", "placeholder": true }
  ],
  "rendered_markdown": "..."
}
```

v1 required element types:
- headings + paragraphs
- lists
- tables
- figure placeholders

**Beta**: add optional bounding boxes `bbox`. to elements and optional `page_label_bbox`.

## 4. Ground truth format
Store ground truth **page-level** using the canonical schema same validator/models as predictions.. Keep `rendered_markdown` for scoring + human review.

In v1, humans type:
- `book_page_label`
- `section_path` optional/partial.


## 4.1. Printed page label book page. capture & validation
### v1 capture
In v1, the labeler manually enters `book_page_label` during ground-truth editing.

### Validation checks run after labeling.
Implement a `bench gt validate` command that performs sanity checks per `document_id`:
- **Duplicates:** same `book_page_label` appears on multiple `pdf_page_number` values flag.
- **Monotonicity:** `book_page_label` should mostly increase with `pdf_page_number` flag large unexpected drops/jumps.
- **Offset stability:** estimate an offset if labels are numeric. and flag outliers

These checks do not change ground truth; they produce a warnings report for humans.


## 5. Parser adapters plugin interface.
Each adapter implements:

- `parsepdf_path, page_numbers, config. -> NativeOutput`
- `to_canonicalnative_output. -> list[CanonicalPage]`

Initial adapters:
- Local: Marker, pdfplumber, Surya
- API-capable stubs feature-flagged.: LlamaParse, Azure Document Intelligence

## 6. Normalization: canonical → standardized Markdown
A single renderer ensures fair comparisons:
- headings: `#`, `##`, …
- lists: `- item`
- tables: normalized pipe tables
- figures: placeholders, e.g. `FIGURE: Figure 2.3 ...`

## 7. Metrics + scoring
### Composite score
- `overall = 0.40 * text_accuracy + 0.60 * structural_fidelity`

### Text accuracy
- edit similarity Levenshtein-based.
- BLEU
- token F1

### Structural fidelity
- structure/tree similarity tree edit / simplified tree edit.
- reading-order accuracy
- heading detection F1

### Traceability metrics reported; low weight in v1.
- printed page label: exact + normalized match rates
- section path: exact + prefix/partial match

Report scores by:
- overall
- per metric
- per “complexity bucket” simple/moderate/complex., when labeled.

## 8. Rotation handling fairness baseline.
Baseline benchmark: **no auto-rotate preprocessing**. Parsers must handle rotated pages. Flag + score failures. Optional experiment mode may auto-rotate and compare..

## 9. Caching & determinism
- Cache raw native outputs to disk.
- Default run: 1 trial.
- Optional `--trials N` to measure variance for nondeterministic parsers; report mean/std.

## 10. CLI commands minimum viable.
- `bench init` → scaffold + default config
- `bench sample --phase smoke|confidence` → write `samples/*.json`
- `bench gt create` → seed ground truth from a chosen parser
- `bench gt edit` → open/print files for manual edits
- `bench run --parsers ... --phase smoke` → raw + canonical + markdown artifacts
- `bench eval --phase smoke` → metrics + per-parser results JSON
- `bench report --phase smoke` → Markdown report + charts + combined_results.json

## 11. Codex 5.3 alignment
v1: deterministic scoring; Codex is optional for:
- suggesting ground-truth edits
- summarizing diffs

beta: Codex-as-judge on flagged pages only, storing rationale as metadata not replacing deterministic scores..

## 12. Acceptance criteria v1.
- Smoke test 15 pages. runs end-to-end and produces:
  - leaderboard CSV/JSON
  - `comparison_report.md`
  - charts png.
  - per-page diff bundles
  - cached raw outputs + canonical JSON + standardized Markdown
- Confidence run supports 50–100 pages.
- Winner selection applies 2% tie-break rules and is reflected in the report.
