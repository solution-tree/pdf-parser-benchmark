"""Tests for PDF ingestion pipeline."""

from pathlib import Path

import pytest

from src.ingest import extract_book_meta, load_and_chunk, strip_boilerplate


def test_sku_extraction():
    """Verify SKU extracted correctly from filename."""
    meta = extract_book_meta("data/pdfs/bkf032_professional-learning-communities.pdf")
    assert meta["sku"] == "bkf032"
    assert "professional" in meta["book_title"].lower()
    assert meta["source"] == "bkf032_professional-learning-communities"


def test_sku_extraction_short_name():
    """Handle short filenames gracefully."""
    meta = extract_book_meta("data/pdfs/bkf032.pdf")
    assert meta["sku"] == "bkf032"


def test_boilerplate_removal():
    """Inject repeated header, assert it's stripped."""
    from llama_index.core.schema import Document

    # Create fake documents with repeated header
    docs = []
    for i in range(10):
        docs.append(
            Document(
                text=f"HEADER LINE REPEATED\nPage {i} content here\nFOOTER REPEATED",
                metadata={"page": i},
            )
        )

    cleaned = strip_boilerplate(docs)

    for doc in cleaned:
        assert "HEADER LINE REPEATED" not in doc.text
        assert "FOOTER REPEATED" not in doc.text
        assert "content here" in doc.text


def test_parse_pdf_extracts_pages(sample_pdf_path):
    """Parse one real PDF, assert pages > 0."""
    from llama_index.core import SimpleDirectoryReader
    from llama_index.readers.file import PyMuPDFReader

    reader = SimpleDirectoryReader(
        input_files=[str(sample_pdf_path)],
        file_extractor={".pdf": PyMuPDFReader()},
        file_metadata=extract_book_meta,
    )
    documents = reader.load_data()
    assert len(documents) > 0


def test_chunk_metadata_keys(sample_pdf_path):
    """Assert every chunk has required metadata keys."""
    nodes = load_and_chunk(
        pdf_dir=sample_pdf_path.parent,
        chunk_size=512,
        chunk_overlap=64,
    )
    assert len(nodes) > 0

    for node in nodes[:5]:  # Check first 5 nodes
        meta = node.metadata
        assert "sku" in meta, f"Missing 'sku' in metadata: {meta.keys()}"
        assert "book_title" in meta, f"Missing 'book_title' in metadata: {meta.keys()}"
        assert "source" in meta, f"Missing 'source' in metadata: {meta.keys()}"
        assert node.get_content(), "Node has no text content"
