"""Tests for FastAPI endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.rag import QueryResult, SourceNode


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    with patch("src.api.routes.get_config") as mock_config, patch(
        "src.api.middleware.get_config"
    ) as mock_mw_config:
        cfg = MagicMock()
        cfg.OPENAI_API_KEY = "sk-test"
        cfg.API_KEY = "test-api-key"
        cfg.REDIS_URL = "redis://localhost:6379"
        cfg.USE_LOCAL_QDRANT = True
        cfg.QDRANT_LOCAL_PATH = "/tmp/test_qdrant"
        cfg.QDRANT_COLLECTION = "test"
        cfg.LLM_MODEL = "gpt-4o"
        cfg.EMBED_MODEL = "text-embedding-3-large"
        cfg.EMBED_DIMENSIONS = 3072
        cfg.SIMILARITY_TOP_K = 5
        cfg.WEB_SEARCH_SCORE_THRESHOLD = 0.65
        cfg.PERPLEXITY_API_KEY = ""
        mock_config.return_value = cfg
        mock_mw_config.return_value = cfg

        from src.api.main import app

        yield TestClient(app)


def test_health_endpoint(client):
    """GET /health returns 200."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "qdrant" in data
    assert "redis" in data


def test_query_requires_auth(client):
    """POST /query without key returns 401."""
    response = client.post("/api/v1/query", json={"query": "What is PLC?"})
    assert response.status_code == 401


def test_query_success(client):
    """POST /query with valid key returns answer."""
    mock_result = QueryResult(
        answer="PLCs are collaborative teams.",
        sources=[
            SourceNode(
                book_title="Test Book",
                sku="bkf032",
                page="10",
                excerpt="Excerpt text...",
                score=0.9,
            )
        ],
        used_web=False,
    )

    with patch("src.api.routes.query", return_value=mock_result), patch(
        "src.api.routes._get_engine", return_value=MagicMock()
    ):
        response = client.post(
            "/api/v1/query",
            json={"query": "What is PLC?"},
            headers={"X-API-Key": "test-api-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert data["answer"] == "PLCs are collaborative teams."
    assert len(data["sources"]) == 1
    assert data["sources"][0]["sku"] == "bkf032"
