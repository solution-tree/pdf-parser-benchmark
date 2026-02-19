"""Metadata schema definitions for the PLC RAG pipeline."""

from typing import List, Literal, Optional, TypedDict

ChunkType = Literal[
    "body_text",
    "reproducible",
    "table",
    "list",
    "chapter_summary",
    "callout",
    "title",
]


class BookMetadata(TypedDict):
    sku: str
    title: str
    authors: List[str]


class MetadataSchema(TypedDict):
    book_title: str
    authors: List[str]
    sku: str
    chapter: Optional[str]
    section: Optional[str]
    page_number: int
    chunk_type: ChunkType
    reproducible_id: Optional[str]
