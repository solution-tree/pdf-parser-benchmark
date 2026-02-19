"""PDF ingestion: manifest.json -> layout-aware parsing -> nodes with rich metadata."""

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from openai import OpenAI
from rich.console import Console
from rich.table import Table

from llama_index.core.schema import TextNode
from llmsherpa.readers import LayoutPDFReader

from src.config import get_config
from src.schema import ChunkType, MetadataSchema

console = Console()

REPRODUCIBLE_PROMPT = (
    "You are an expert in Professional Learning Communities. This image is a reproducible\n"
    "or worksheet from a PLC guidebook. Describe it in detail, including its title,\n"
    'purpose, key sections, and any instructions. If the reproducible is numbered\n'
    '(e.g., "Reproducible 4.3"), extract that number. Format your description as a\n'
    "structured markdown document."
)

# llmsherpa tag -> ChunkType
_TAG_MAP: dict[str, ChunkType] = {
    "header": "title",
    "para": "body_text",
    "list_item": "list",
    "table": "table",
    "table_row": "table",
}


def load_manifest(manifest_path: Path) -> list[dict]:
    """Load the book manifest from JSON."""
    return json.loads(manifest_path.read_text())


def get_landscape_pages(pdf_path: Path) -> set[int]:
    """Return 0-based page indices of landscape-oriented (rotated) pages."""
    landscape: set[int] = set()
    with fitz.open(str(pdf_path)) as doc:
        for i, page in enumerate(doc):
            if page.rotation in (90, 270):
                landscape.add(i)
    return landscape


def render_page_as_base64(pdf_path: Path, page_idx: int, dpi: int = 150) -> str:
    """Render a PDF page to a base64-encoded PNG."""
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_idx]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        return base64.b64encode(pix.tobytes("png")).decode()


def extract_reproducible_id(text: str) -> Optional[str]:
    """Extract reproducible identifier (e.g. '4.3') from GPT-4o response text."""
    match = re.search(r"[Rr]eproducible\s+([\d]+\.[\d]+|[\d]+[A-Za-z]?)", text)
    return match.group(1) if match else None


def process_reproducible_page(
    pdf_path: Path,
    page_idx: int,
    book: dict,
    openai_client: OpenAI,
) -> TextNode:
    """Render a landscape page as image and describe it with GPT-4o vision."""
    image_b64 = render_page_as_base64(pdf_path, page_idx)

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                            "detail": "high",
                        },
                    },
                    {"type": "text", "text": REPRODUCIBLE_PROMPT},
                ],
            }
        ],
        max_tokens=1024,
    )

    description = response.choices[0].message.content or ""
    repro_id = extract_reproducible_id(description)

    metadata: MetadataSchema = {
        "book_title": book["title"],
        "authors": book.get("authors", []),
        "sku": book["sku"].lower(),
        "chapter": None,
        "section": None,
        "page_number": page_idx + 1,
        "chunk_type": "reproducible",
        "reproducible_id": repro_id,
    }

    return TextNode(text=description, metadata=metadata)


def infer_chunk_type(tag: str) -> ChunkType:
    """Map a llmsherpa chunk tag to our ChunkType."""
    tag_lower = (tag or "").lower().strip()
    for key, val in _TAG_MAP.items():
        if key in tag_lower:
            return val
    return "body_text"


def process_book(
    book: dict,
    pdf_base_dir: Path,
    layout_reader: LayoutPDFReader,
    openai_client: OpenAI,
) -> list[TextNode]:
    """Parse one book and return TextNodes with MetadataSchema-conforming metadata."""
    sku = book["sku"].lower()
    pdf_path = pdf_base_dir / book["expected_pdf_filename"]

    if not pdf_path.exists():
        console.print(f"[yellow]  Skipping {sku}: PDF not found at {pdf_path}[/yellow]")
        return []

    console.print(f"[bold]Processing {sku}:[/bold] {book['title'][:70]}")

    # Step 1: Detect landscape (rotated) pages before layout parsing
    landscape_pages = get_landscape_pages(pdf_path)
    if landscape_pages:
        console.print(
            f"  [cyan]{len(landscape_pages)} landscape page(s) detected -> GPT-4o vision[/cyan]"
        )

    nodes: list[TextNode] = []

    # Step 2: Multimodal processing for each landscape page
    for page_idx in sorted(landscape_pages):
        try:
            node = process_reproducible_page(pdf_path, page_idx, book, openai_client)
            nodes.append(node)
        except Exception as e:
            console.print(f"  [red]Error on landscape page {page_idx + 1}: {e}[/red]")

    # Step 3: Layout-aware parsing of the full PDF
    try:
        doc = layout_reader.read_pdf(str(pdf_path))
    except Exception as e:
        console.print(f"  [red]LayoutPDFReader failed for {sku}: {e}[/red]")
        return nodes

    # Step 4: Iterate all chunks; track chapter/section hierarchy
    current_chapter: Optional[str] = None
    current_section: Optional[str] = None

    for chunk in doc.chunks():
        page_idx: Optional[int] = getattr(chunk, "page_idx", None)

        # Skip pages already handled by the multimodal path
        if page_idx is not None and page_idx in landscape_pages:
            continue

        tag: str = getattr(chunk, "tag", "") or ""
        level: Optional[int] = getattr(chunk, "level", None)
        text = chunk.to_text().strip()

        if not text:
            continue

        # Update running chapter/section based on header level
        if "header" in tag.lower():
            if level is None or level <= 1:
                current_chapter = text
                current_section = None
            else:
                current_section = text

        chunk_type = infer_chunk_type(tag)
        page_number = (page_idx + 1) if page_idx is not None else 0

        metadata: MetadataSchema = {
            "book_title": book["title"],
            "authors": book.get("authors", []),
            "sku": sku,
            "chapter": current_chapter,
            "section": current_section,
            "page_number": page_number,
            "chunk_type": chunk_type,
            "reproducible_id": None,
        }

        nodes.append(TextNode(text=text, metadata=metadata))

    console.print(f"  -> [green]{len(nodes)} nodes[/green]")
    return nodes


def save_nodes(nodes: list[TextNode], output_path: Path) -> None:
    """Serialize nodes to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [node.to_dict() for node in nodes]
    output_path.write_text(json.dumps(data, indent=2, default=str))


def build_summary_table(nodes: list[TextNode]) -> Table:
    """Build a Rich table summarising ingested nodes by book."""
    table = Table(title="Ingestion Summary")
    table.add_column("SKU", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Nodes", justify="right")
    table.add_column("Reproducibles", justify="right")
    table.add_column("Status", style="bold")

    sku_data: dict[str, dict] = {}
    for node in nodes:
        meta = node.metadata
        sku = meta.get("sku", "unknown")
        if sku not in sku_data:
            sku_data[sku] = {
                "title": meta.get("book_title", "Unknown"),
                "nodes": 0,
                "reproducibles": 0,
            }
        sku_data[sku]["nodes"] += 1
        if meta.get("chunk_type") == "reproducible":
            sku_data[sku]["reproducibles"] += 1

    for sku, info in sorted(sku_data.items()):
        table.add_row(
            sku,
            info["title"][:60],
            str(info["nodes"]),
            str(info["reproducibles"]),
            "[green]OK[/green]",
        )

    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PDFs into structured nodes")
    parser.add_argument("--pdf-dir", type=Path, default=None, help="PDF directory")
    parser.add_argument(
        "--force", action="store_true", help="Re-ingest even if nodes.json exists"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    config = get_config()

    if not config.OPENAI_API_KEY:
        console.print(
            "[red][ERROR] OPENAI_API_KEY is not set. Add it to your .env file.[/red]"
        )
        sys.exit(1)

    pdf_dir = args.pdf_dir or config.PDF_DIR
    output_path = config.PROCESSED_DIR / "nodes.json"
    manifest_path = Path("data/manifest.json")

    if output_path.exists() and not args.force:
        console.print(
            f"[yellow]nodes.json already exists at {output_path}. "
            "Use --force to re-ingest.[/yellow]"
        )
        sys.exit(0)

    books = load_manifest(manifest_path)
    console.print(f"[bold]Loaded {len(books)} books from manifest[/bold]\n")

    openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    layout_reader = LayoutPDFReader(config.LLMSHERPA_API_URL)

    all_nodes: list[TextNode] = []
    for book in books:
        book_nodes = process_book(book, pdf_dir, layout_reader, openai_client)
        all_nodes.extend(book_nodes)

    save_nodes(all_nodes, output_path)
    console.print(f"\n[green]Saved {len(all_nodes)} nodes to {output_path}[/green]\n")
    console.print(build_summary_table(all_nodes))


if __name__ == "__main__":
    main()
