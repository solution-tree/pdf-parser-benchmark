"""Application configuration via pydantic-settings. All values read from .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    # Paths
    PDF_DIR: Path = Path("data/pdfs")
    PROCESSED_DIR: Path = Path("data/processed")
    QDRANT_LOCAL_PATH: Path = Path("data/qdrant")

    # OpenAI
    OPENAI_API_KEY: str
    LLM_MODEL: str = "gpt-4o"
    EMBED_MODEL: str = "text-embedding-3-large"
    EMBED_DIMENSIONS: int = 3072  # text-embedding-3-large native

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "plc_books"
    USE_LOCAL_QDRANT: bool = True  # False in production

    # RAG
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64
    SIMILARITY_TOP_K: int = 5

    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL_SECONDS: int = 86400  # 24h

    # Perplexity
    PERPLEXITY_API_KEY: str = ""
    PERPLEXITY_MODEL: str = "llama-3.1-sonar-large-128k-online"
    WEB_SEARCH_SCORE_THRESHOLD: float = 0.65  # fallback to web if best score < this

    # API
    API_KEY: str = ""
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/plc_kb"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def model_post_init(self, __context):
        self.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        if self.USE_LOCAL_QDRANT:
            self.QDRANT_LOCAL_PATH.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_config() -> Config:
    return Config()
