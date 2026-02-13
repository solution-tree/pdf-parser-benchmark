#!/usr/bin/env python3
"""Rename PDFs in-place to canonical filenames based on books_autoname_map.csv and/or manifest.json.

Intended location: data/pdfs/ (run it from that folder):

    python rename_pdfs.py --mapping ../books_autoname_map.csv --manifest ../manifest.json

Default behavior is DRY RUN. Add --apply to actually rename.

What it does:
1) Loads mapping CSV (sku/title/document_id/pdf_filename)
2) Optionally loads manifest.json and writes back current_pdf_path + page_count (if pypdf installed)
3) Matches existing PDFs (human filenames) to book titles using fuzzy matching
4) Renames files to expected canonical filenames (never overwrites)
5) Writes rename_report.csv for auditing
"""

import argparse
import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Tuple


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\.pdf$", "", s)
    s = re.sub(r"[\u00ae\u2122]", "", s)   # ® ™
    s = re.sub(r"\[.*?\]", " ", s)         # [Second Edition]
    s = re.sub(r"\(.*?\)", " ", s)         # (Second Edition)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class Book:
    sku: str
    title: str
    document_id: str
    pdf_filename: str
    expected_pdf_path: Optional[str] = None


def load_mapping(mapping_csv: Path) -> List[Book]:
    with mapping_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"sku", "title", "document_id", "pdf_filename"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Mapping CSV missing columns: {sorted(missing)}")
        books: List[Book] = []
        for r in reader:
            books.append(Book(
                sku=r["sku"].strip(),
                title=r["title"].strip(),
                document_id=r["document_id"].strip(),
                pdf_filename=r["pdf_filename"].strip(),
                expected_pdf_path=(r.get("pdf_path_expected") or "").strip() or None,
            ))
        return books


def list_pdfs(pdf_dir: Path) -> List[Path]:
    return sorted([p for p in pdf_dir.glob("*.pdf") if p.is_file()])


def best_match(book: Book, pdfs: List[Path]) -> Tuple[Optional[Path], float, Optional[Path], float]:
    tgt = normalize(book.title)
    scored = [(similarity(tgt, normalize(p.name)), p) for p in pdfs]
    scored.sort(reverse=True, key=lambda x: x[0])
    if not scored:
        return None, 0.0, None, 0.0
    best_s, best_p = scored[0]
    if len(scored) > 1:
        second_s, second_p = scored[1]
    else:
        second_s, second_p = 0.0, None
    return best_p, best_s, second_p, second_s


def try_page_count(pdf_path: Path) -> Optional[int]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return None
    try:
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default=".", help="Directory containing PDFs (default: current directory)")
    ap.add_argument("--mapping", default="../books_autoname_map.csv", help="Path to books_autoname_map.csv")
    ap.add_argument("--manifest", default="../manifest.json", help="Path to manifest.json (will be updated if exists)")
    ap.add_argument("--min-score", type=float, default=0.86, help="Minimum similarity score to accept match (0..1)")
    ap.add_argument("--min-gap", type=float, default=0.05, help="Min gap between best and second-best to avoid ambiguity")
    ap.add_argument("--apply", action="store_true", help="Actually rename files")
    ap.add_argument("--report", default="rename_report.csv", help="Write audit report CSV")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir).resolve()
    mapping_csv = Path(args.mapping).resolve()
    manifest_path = Path(args.manifest).resolve()

    if not pdf_dir.exists():
        raise SystemExit(f"PDF dir not found: {pdf_dir}")
    if not mapping_csv.exists():
        raise SystemExit(f"Mapping CSV not found: {mapping_csv}")

    books = load_mapping(mapping_csv)
    pdfs = list_pdfs(pdf_dir)
    if not pdfs:
        raise SystemExit(f"No PDFs found in {pdf_dir}")

    manifest = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = None

    used_sources = set()
    plan = []      # rows for report
    safe = []      # (src, dst, book, score)

    for book in books:
        best_p, best_s, second_p, second_s = best_match(book, pdfs)
        if best_p is None:
            plan.append((book.sku, book.title, "", book.pdf_filename, 0.0, "SKIP", "no_pdfs_found"))
            continue

        gap = best_s - second_s
        ambiguous = (best_s < args.min_score) or (gap < args.min_gap) or (best_p in used_sources)
        if ambiguous:
            plan.append((book.sku, book.title, best_p.name, book.pdf_filename, best_s, "SKIP",
                         f"ambiguous(best={best_s:.3f}, second={second_s:.3f}, gap={gap:.3f})"))
            continue

        used_sources.add(best_p)
        dst = pdf_dir / book.pdf_filename
        if dst.exists() and dst.resolve() != best_p.resolve():
            plan.append((book.sku, book.title, best_p.name, book.pdf_filename, best_s, "SKIP", "target_exists"))
            continue

        safe.append((best_p, dst, book, best_s))
        plan.append((book.sku, book.title, best_p.name, book.pdf_filename, best_s, "OK", ""))

    report_path = (pdf_dir / args.report).resolve()
    with report_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "title", "current_filename", "new_filename", "match_score", "status", "note"])
        for row in plan:
            w.writerow(row)

    print(f"\nPDF dir: {pdf_dir}")
    print(f"Found PDFs: {len(pdfs)}")
    print(f"Books in mapping: {len(books)}")
    print(f"Safe renames planned: {len(safe)}")
    print(f"Audit report: {report_path}\n")

    for src, dst, book, score in safe:
        print(f"{src.name}  ->  {dst.name}   (score={score:.3f}, sku={book.sku})")

    if not args.apply:
        print("\nDRY RUN ONLY. Re-run with --apply to actually rename.")
    else:
        renamed = 0
        for src, dst, book, score in safe:
            if dst.exists() and dst.resolve() != src.resolve():
                print(f"SKIP (target exists): {dst.name}")
                continue
            if src.resolve() == dst.resolve():
                continue
            os.rename(src, dst)
            renamed += 1
        print(f"\nRenamed {renamed} files.")

    # Update manifest with current paths + page counts if possible
    if manifest is not None:
        for m in manifest:
            if not isinstance(m, dict):
                continue
            exp_name = m.get("expected_pdf_filename") or Path(m.get("expected_pdf_path", "")).name
            if not exp_name:
                continue
            p = pdf_dir / exp_name
            if p.exists():
                m["current_pdf_path"] = str(p)
                pc = try_page_count(p)
                if pc is not None:
                    m["pdf_page_count"] = pc
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"\nUpdated manifest: {manifest_path}")
        except Exception as e:
            print(f"\nWARNING: Failed to update manifest: {e}")


if __name__ == "__main__":
    main()
