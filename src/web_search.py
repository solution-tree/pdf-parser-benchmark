"""Perplexity API fallback when book context score is low."""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import Config

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def perplexity_search(query: str, config: Config) -> str:
    """Returns web search result as a string to append to RAG context."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            PERPLEXITY_API_URL,
            headers={"Authorization": f"Bearer {config.PERPLEXITY_API_KEY}"},
            json={
                "model": config.PERPLEXITY_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a PLC education expert. Answer concisely with sources.",
                    },
                    {"role": "user", "content": query},
                ],
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
