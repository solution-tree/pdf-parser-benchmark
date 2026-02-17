"""PDF ingestion: parse PDFs → chunk → save to data/processed/nodes.json."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table

from llama_index.core import SimpleDirectoryReader
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.readers.file import PyMuPDFReader

from src.config import get_config

console = Console()


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
        line
        for line, count in counts.items()
        if count > len(documents) * 0.4 and len(line) < 100
    }
    for doc in documents:
        clean = "\n".join(
            l for l in doc.text.splitlines() if l.strip() not in boilerplate
        )
        doc.set_content(clean)
    return documents


def load_and_chunk(
    pdf_dir: Path, chunk_size: int = 512, chunk_overlap: int = 64
) -> list:
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
        file_extractor={".pdf": PyMuPDFReader()},
        file_metadata=extract_book_meta,
    )
    documents = reader.load_data(show_progress=True)

    documents = strip_boilerplate(documents)

    pipeline = IngestionPipeline(
        transformations=[
            SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
        ]
    )
    nodes = pipeline.run(documents=documents, show_progress=True)
    return nodes


def save_nodes(nodes: list, output_path: Path) -> None:
    """Serialize nodes to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [node.to_dict() for node in nodes]
    output_path.write_text(json.dumps(data, indent=2, default=str))


def build_summary_table(nodes: list) -> Table:
    """Build a Rich table summarizing ingested nodes by book."""
    table = Table(title="Ingestion Summary")
    table.add_column("SKU", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Pages", justify="right")
    table.add_column("Nodes", justify="right")
    table.add_column("Status", style="bold")

    # Group by SKU
    sku_data: dict[str, dict] = {}
    for node in nodes:
        meta = node.metadata
        sku = meta.get("sku", "unknown")
        if sku not in sku_data:
            sku_data[sku] = {
                "title": meta.get("book_title", "Unknown"),
                "pages": set(),
                "nodes": 0,
            }
        page = meta.get("page_label", meta.get("source", ""))
        sku_data[sku]["pages"].add(page)
        sku_data[sku]["nodes"] += 1

    for sku, info in sorted(sku_data.items()):
        table.add_row(
            sku,
            info["title"][:60],
            str(len(info["pages"])),
            str(info["nodes"]),
            "[green]OK[/green]",
        )

    return table


def main():
    parser = argparse.ArgumentParser(description="Ingest PDFs into chunks")
    parser.add_argument("--pdf-dir", type=Path, default=None, help="PDF directory")
    parser.add_argument("--force", action="store_true", help="Re-ingest even if nodes.json exists")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    config = get_config()
    pdf_dir = args.pdf_dir or config.PDF_DIR
    output_path = config.PROCESSED_DIR / "nodes.json"

    if output_path.exists() and not args.force:
        console.print(
            f"[yellow]nodes.json already exists at {output_path}. "
            "Use --force to re-ingest.[/yellow]"
        )
        sys.exit(0)

    console.print(f"[bold]Ingesting PDFs from {pdf_dir}...[/bold]")

    nodes = load_and_chunk(
        pdf_dir=pdf_dir,
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    save_nodes(nodes, output_path)
    console.print(f"\n[green]Saved {len(nodes)} nodes to {output_path}[/green]\n")

    table = build_summary_table(nodes)
    console.print(table)


if __name__ == "__main__":
    main()
