"""Tests for RAG query engine."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.rag import QueryResult, SourceNode, parse_source_nodes, query


def _make_mock_source_node(text="sample text", sku="bkf032", score=0.85):
    """Create a mock source node."""
    node = MagicMock()
    node.node.metadata = {
        "sku": sku,
        "book_title": "Test Book",
        "page_label": "42",
        "source": "test_source",
    }
    node.node.get_content.return_value = text
    node.score = score
    return node


def test_query_returns_result():
    """Mock query engine returns a QueryResult."""
    mock_engine = MagicMock()
    mock_response = MagicMock()
    mock_response.source_nodes = [_make_mock_source_node()]
    mock_response.__str__ = lambda self: "This is the answer."
    mock_engine.query.return_value = mock_response

    config = MagicMock()
    config.WEB_SEARCH_SCORE_THRESHOLD = 0.65
    config.PERPLEXITY_API_KEY = ""

    result = query(mock_engine, "What are PLCs?", config)

    assert isinstance(result, QueryResult)
    assert "answer" in result.answer.lower() or len(result.answer) > 0


def test_sources_populated():
    """Assert sources list is non-empty."""
    mock_engine = MagicMock()
    mock_response = MagicMock()
    mock_response.source_nodes = [
        _make_mock_source_node(sku="bkf032"),
        _make_mock_source_node(sku="bkf840"),
    ]
    mock_response.__str__ = lambda self: "Answer text."
    mock_engine.query.return_value = mock_response

    config = MagicMock()
    config.WEB_SEARCH_SCORE_THRESHOLD = 0.65
    config.PERPLEXITY_API_KEY = ""

    result = query(mock_engine, "test query", config)

    assert len(result.sources) == 2
    assert result.sources[0].sku == "bkf032"
    assert result.sources[1].sku == "bkf840"


def test_parse_source_nodes():
    """Test parsing source nodes from response."""
    mock_response = MagicMock()
    mock_response.source_nodes = [
        _make_mock_source_node(text="Excerpt from book", sku="bkf705", score=0.92),
    ]

    sources = parse_source_nodes(mock_response)

    assert len(sources) == 1
    assert sources[0].sku == "bkf705"
    assert sources[0].score == 0.92
    assert sources[0].page == "42"
    assert sources[0].book_title == "Test Book"


def test_low_score_triggers_web_flag():
    """When scores are low and Perplexity key is set, used_web should be True."""
    mock_engine = MagicMock()
    mock_response = MagicMock()
    mock_response.source_nodes = [_make_mock_source_node(score=0.3)]
    mock_response.__str__ = lambda self: "Low confidence answer."
    mock_engine.query.return_value = mock_response

    config = MagicMock()
    config.WEB_SEARCH_SCORE_THRESHOLD = 0.65
    config.PERPLEXITY_API_KEY = "pplx-test-key"
    config.PERPLEXITY_MODEL = "llama-3.1-sonar-large-128k-online"

    with patch("src.rag.asyncio.run") as mock_run:
        mock_run.return_value = "Web search result text"
        result = query(mock_engine, "obscure question", config)

    assert result.used_web is True
    assert "[WEB]" in result.answer
