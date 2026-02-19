"""RAG query engine: load existing Qdrant index, run queries, return structured results."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI as OpenAIClient
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore

from src.config import Config
from src.embed import get_qdrant_client
from src.web_search import perplexity_search


@dataclass
class SourceNode:
    book_title: str
    sku: str
    page: str
    excerpt: str
    score: float
    chapter: Optional[str] = None
    section: Optional[str] = None
    chunk_type: str = "body_text"


@dataclass
class QueryResult:
    answer: str
    sources: list[SourceNode] = field(default_factory=list)
    used_web: bool = False


SYSTEM_PROMPT = """You are a knowledgeable coach on Professional Learning Communities (PLCs) at Work.
Answer questions based ONLY on the provided book excerpts.
Always cite your sources using the format: [SKU] Book Title, page N.
If the information is not in the provided context, say so clearly.
Be specific and actionable in your responses."""

FILTER_EXTRACTION_PROMPT = """You are a query analyzer for a Professional Learning Communities (PLC) book database.
Given a user query, extract any specific filters that should be applied when searching the database.
Return a JSON object with these fields:
- "book_titles": list of exact or partial book titles mentioned (empty list if none)
- "authors": list of author last names mentioned (empty list if none)
- "chunk_type": one of ["reproducible", "table", "list", "body_text", "title", null] if a specific content type is requested
- "chapter": chapter name or number if specifically mentioned (null otherwise)

Return ONLY valid JSON, no other text. If no filters can be confidently identified, return {}.

Examples:
- "Find reproducibles about collaborative teams" -> {{"book_titles": [], "authors": [], "chunk_type": "reproducible", "chapter": null}}
- "What does Learning by Doing say about assessment?" -> {{"book_titles": ["Learning by Doing"], "authors": [], "chunk_type": null, "chapter": null}}
- "Compare DuFour and Muhammad on school culture" -> {{"book_titles": [], "authors": ["DuFour", "Muhammad"], "chunk_type": null, "chapter": null}}
- "What are the four critical questions of a PLC?" -> {{}}

User query: {query}"""


def load_index(config: Config) -> VectorStoreIndex:
    """Load the VectorStoreIndex from the existing Qdrant collection (never re-embeds)."""
    client = get_qdrant_client(config)
    vector_store = QdrantVectorStore(
        client=client, collection_name=config.QDRANT_COLLECTION
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    Settings.llm = OpenAI(
        model=config.LLM_MODEL,
        api_key=config.OPENAI_API_KEY,
        system_prompt=SYSTEM_PROMPT,
    )
    Settings.embed_model = OpenAIEmbedding(
        model=config.EMBED_MODEL,
        api_key=config.OPENAI_API_KEY,
        dimensions=config.EMBED_DIMENSIONS,
    )

    return VectorStoreIndex.from_vector_store(
        vector_store, storage_context=storage_context
    )


# Backwards-compatible alias used by chat.py and api/routes.py
def load_query_engine(config: Config) -> VectorStoreIndex:
    """Alias for load_index — callers receive a VectorStoreIndex, not a bare engine."""
    return load_index(config)


def extract_filters_from_query(query_text: str, config: Config) -> dict:
    """Use GPT-4o to extract metadata filters from a user query.

    Returns a dict with keys: book_titles, authors, chunk_type, chapter.
    Returns an empty dict if no filters can be confidently extracted.
    """
    try:
        client = OpenAIClient(api_key=config.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": FILTER_EXTRACTION_PROMPT.format(query=query_text),
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=200,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception:
        return {}


def build_metadata_filters(filters_dict: dict) -> Optional[MetadataFilters]:
    """Convert a filter dict from extract_filters_from_query into MetadataFilters."""
    if not filters_dict:
        return None

    book_titles: list[str] = filters_dict.get("book_titles") or []
    chunk_type: Optional[str] = filters_dict.get("chunk_type")

    book_filters = [
        MetadataFilter(
            key="book_title",
            value=title,
            operator=FilterOperator.CONTAINS,
        )
        for title in book_titles
    ]

    type_filters = (
        [MetadataFilter(key="chunk_type", value=chunk_type, operator=FilterOperator.EQ)]
        if chunk_type
        else []
    )

    # If multiple book titles, OR them together; AND with chunk_type filter if present
    if len(book_filters) > 1:
        combined: list = [
            MetadataFilters(filters=book_filters, condition=FilterCondition.OR)
        ] + type_filters
        return MetadataFilters(filters=combined, condition=FilterCondition.AND)

    all_filters = book_filters + type_filters
    if not all_filters:
        return None

    return MetadataFilters(filters=all_filters, condition=FilterCondition.AND)


def parse_source_nodes(response) -> list[SourceNode]:
    """Extract SourceNode objects from a LlamaIndex response."""
    sources = []
    for node_with_score in response.source_nodes:
        meta = node_with_score.node.metadata
        # page_number (int) from new schema; fall back to page_label for legacy nodes
        page = meta.get("page_number") or meta.get("page_label") or meta.get("source", "?")
        sources.append(
            SourceNode(
                book_title=meta.get("book_title", "Unknown"),
                sku=meta.get("sku", ""),
                page=str(page),
                excerpt=node_with_score.node.get_content()[:300],
                score=node_with_score.score or 0.0,
                chapter=meta.get("chapter"),
                section=meta.get("section"),
                chunk_type=meta.get("chunk_type", "body_text"),
            )
        )
    return sources


def query(index: VectorStoreIndex, query_text: str, config: Config) -> QueryResult:
    """Run a RAG query with dynamic metadata filtering and optional web fallback."""
    # Step 1: Extract filters from query
    filters_dict = extract_filters_from_query(query_text, config)
    llama_filters = build_metadata_filters(filters_dict)

    # Step 2: Build engine with filters
    engine = index.as_query_engine(
        similarity_top_k=config.SIMILARITY_TOP_K,
        response_mode="tree_summarize",
        filters=llama_filters,
    )

    response = engine.query(query_text)
    sources = parse_source_nodes(response)

    # Step 3: Fallback — if filtered query returns < 3 results, retry without filters
    if llama_filters and len(sources) < 3:
        engine_unfiltered = index.as_query_engine(
            similarity_top_k=config.SIMILARITY_TOP_K,
            response_mode="tree_summarize",
        )
        response = engine_unfiltered.query(query_text)
        sources = parse_source_nodes(response)

    answer = str(response)

    # Step 4: Perplexity web search fallback if RAG confidence is low
    used_web = False
    if sources:
        best_score = max(s.score for s in sources)
        if best_score < config.WEB_SEARCH_SCORE_THRESHOLD and config.PERPLEXITY_API_KEY:
            try:
                web_result = asyncio.run(perplexity_search(query_text, config))
                answer += f"\n\n[WEB] Additional context from web search:\n{web_result}"
                used_web = True
            except Exception:
                pass  # Web search failure is non-fatal

    return QueryResult(answer=answer, sources=sources, used_web=used_web)
