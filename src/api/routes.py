"""API routes: /health, /query, /ingest."""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from src.config import get_config
from src.embed import build_index, get_qdrant_client
from src.rag import QueryResult, load_index, query

router = APIRouter()

# Lazy-loaded query engine
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        config = get_config()
        _engine = load_index(config)
    return _engine


class QueryRequest(BaseModel):
    query: str
    use_web: bool = False


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    used_web: bool


class HealthResponse(BaseModel):
    status: str
    qdrant: bool
    redis: bool


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    config = get_config()

    # Check Qdrant
    qdrant_ok = False
    try:
        client = get_qdrant_client(config)
        client.get_collections()
        qdrant_ok = True
    except Exception:
        pass

    # Check Redis
    redis_ok = False
    try:
        import redis.asyncio as redis_lib

        r = redis_lib.from_url(config.REDIS_URL)
        await r.ping()
        redis_ok = True
        await r.aclose()
    except Exception:
        pass

    return HealthResponse(status="ok", qdrant=qdrant_ok, redis=redis_ok)


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest):
    """Query the PLC knowledge base."""
    config = get_config()

    if not config.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    engine = _get_engine()
    result: QueryResult = query(engine, request.query, config)

    sources = [
        {
            "book_title": s.book_title,
            "sku": s.sku,
            "page": s.page,
            "excerpt": s.excerpt,
            "score": s.score,
        }
        for s in result.sources
    ]

    return QueryResponse(answer=result.answer, sources=sources, used_web=result.used_web)


def _run_ingest():
    """Background ingestion task."""
    config = get_config()
    build_index(config, force=True)


@router.post("/ingest")
async def ingest_endpoint(background_tasks: BackgroundTasks):
    """Trigger PDF ingestion as a background task."""
    background_tasks.add_task(_run_ingest)
    return {"status": "ingestion_started"}
