"""RAG query engine: load existing Qdrant index, run queries, return structured results."""

import asyncio
from dataclasses import dataclass, field

from llama_index.core import Settings, StorageContext, VectorStoreIndex
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


def load_query_engine(config: Config):
    """Load query engine from existing Qdrant collection (never re-embeds)."""
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

    index = VectorStoreIndex.from_vector_store(
        vector_store, storage_context=storage_context
    )
    return index.as_query_engine(
        similarity_top_k=config.SIMILARITY_TOP_K,
        response_mode="tree_summarize",
    )


def parse_source_nodes(response) -> list[SourceNode]:
    """Extract SourceNode objects from a LlamaIndex response."""
    sources = []
    for node_with_score in response.source_nodes:
        meta = node_with_score.node.metadata
        sources.append(
            SourceNode(
                book_title=meta.get("book_title", "Unknown"),
                sku=meta.get("sku", ""),
                page=meta.get("page_label", meta.get("source", "?")),
                excerpt=node_with_score.node.get_content()[:300],
                score=node_with_score.score or 0.0,
            )
        )
    return sources


def query(engine, query_text: str, config: Config) -> QueryResult:
    """Run a RAG query and optionally fall back to web search."""
    response = engine.query(query_text)
    sources = parse_source_nodes(response)
    answer = str(response)

    # Check if we should fall back to web search
    used_web = False
    if sources:
        best_score = max(s.score for s in sources)
        if (
            best_score < config.WEB_SEARCH_SCORE_THRESHOLD
            and config.PERPLEXITY_API_KEY
        ):
            try:
                web_result = asyncio.run(perplexity_search(query_text, config))
                answer += f"\n\n[WEB] Additional context from web search:\n{web_result}"
                used_web = True
            except Exception:
                pass  # Web search failure is non-fatal

    return QueryResult(answer=answer, sources=sources, used_web=used_web)
