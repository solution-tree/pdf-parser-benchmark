"""Shared test fixtures."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config


@pytest.fixture
def config(tmp_path):
    """Test config with temporary directories."""
    return Config(
        OPENAI_API_KEY="sk-test-key-fake",
        PDF_DIR=Path("data/pdfs"),
        PROCESSED_DIR=tmp_path / "processed",
        QDRANT_LOCAL_PATH=tmp_path / "qdrant",
        USE_LOCAL_QDRANT=True,
        QDRANT_COLLECTION="test_plc_books",
        REDIS_URL="redis://localhost:6379",
        API_KEY="test-api-key",
    )


@pytest.fixture
def sample_pdf_path():
    """Path to a real sample PDF for integration tests."""
    pdf_dir = Path("data/pdfs")
    pdfs = list(pdf_dir.glob("*.pdf"))
    if pdfs:
        return pdfs[0]
    pytest.skip("No PDFs found in data/pdfs/")


@pytest.fixture
def mock_openai():
    """Mock OpenAI API calls."""
    with patch("llama_index.llms.openai.OpenAI") as mock_llm, patch(
        "llama_index.embeddings.openai.OpenAIEmbedding"
    ) as mock_embed:
        mock_llm_instance = MagicMock()
        mock_llm.return_value = mock_llm_instance
        mock_embed_instance = MagicMock()
        mock_embed.return_value = mock_embed_instance
        yield {"llm": mock_llm_instance, "embed": mock_embed_instance}
