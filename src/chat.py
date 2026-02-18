"""CLI REPL chat interface using prompt_toolkit + rich."""

import argparse
import asyncio
import os
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from typing import Optional

from src.cache import get_cached, make_cache_key, set_cached
from src.config import get_config
from src.rag import QueryResult, load_query_engine, query
from src.web_search import perplexity_search

console = Console()

# Store last query result for `sources` command
_last_result: Optional[QueryResult] = None


def connect_redis(config):
    """Try to connect to Redis. Returns client or None if unavailable."""
    try:
        import redis.asyncio as redis

        r = redis.from_url(config.REDIS_URL, decode_responses=True)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(r.ping())
        return r
    except Exception as e:
        console.print(f"[yellow]Redis unavailable ({e}). Running without cache.[/yellow]")
        return None


def display_result(result: QueryResult) -> None:
    """Display query result with Rich formatting."""
    # Answer panel
    console.print(Panel(result.answer, title="Answer", border_style="bright_blue"))

    # Sources table
    if result.sources:
        table = Table(title="Sources")
        table.add_column("Book", style="green")
        table.add_column("SKU", style="cyan")
        table.add_column("Page", justify="right")
        table.add_column("Score", justify="right")

        for src in result.sources:
            prefix = "[WEB] " if result.used_web else ""
            table.add_row(
                f"{prefix}{src.book_title[:50]}",
                src.sku,
                str(src.page),
                f"{src.score:.3f}",
            )
        console.print(table)


def display_sources_detail(result: QueryResult) -> None:
    """Display full source excerpts from last query."""
    if not result or not result.sources:
        console.print("[yellow]No sources from last query.[/yellow]")
        return

    for i, src in enumerate(result.sources, 1):
        console.print(
            Panel(
                src.excerpt,
                title=f"[{src.sku}] {src.book_title}, page {src.page} (score: {src.score:.3f})",
                border_style="dim",
            )
        )


def display_help() -> None:
    """Show commands table."""
    table = Table(title="Commands")
    table.add_column("Command", style="cyan")
    table.add_column("Description")
    table.add_row("quit / exit", "Exit the chat")
    table.add_row("clear", "Clear the screen")
    table.add_row("sources", "Show full excerpts from last query")
    table.add_row("help", "Show this help table")
    table.add_row("!web <query>", "Force Perplexity web search")
    table.add_row("<any text>", "Query the PLC knowledge base")
    console.print(table)


def handle_query(engine, user_input: str, config, redis_client) -> QueryResult:
    """Process a user query, checking cache first."""
    global _last_result

    cache_key = make_cache_key(user_input, config.LLM_MODEL, config.SIMILARITY_TOP_K)

    # Check cache
    if redis_client:
        try:
            cached = asyncio.get_event_loop().run_until_complete(
                get_cached(redis_client, cache_key)
            )
            if cached:
                console.print("[dim](cached)[/dim]")
                result = QueryResult(
                    answer=cached["answer"],
                    sources=[],
                    used_web=cached.get("used_web", False),
                )
                _last_result = result
                return result
        except Exception:
            pass  # Cache errors are non-fatal

    result = query(engine, user_input, config)

    # Store in cache
    if redis_client:
        try:
            cache_data = {
                "answer": result.answer,
                "used_web": result.used_web,
            }
            asyncio.get_event_loop().run_until_complete(
                set_cached(redis_client, cache_key, cache_data, config.CACHE_TTL_SECONDS)
            )
        except Exception:
            pass  # Cache errors are non-fatal

    _last_result = result
    return result


def main():
    global _last_result

    parser = argparse.ArgumentParser(description="PLC Knowledge Base Chat")
    parser.add_argument("--query", type=str, default=None, help="Single-shot query mode")
    args = parser.parse_args()

    config = get_config()

    # Validate API key
    if not config.OPENAI_API_KEY:
        console.print("[red][ERROR] OPENAI_API_KEY is not set. Add it to your .env file.[/red]")
        sys.exit(1)

    # Load query engine
    with console.status("[bold green]Loading RAG engine..."):
        engine = load_query_engine(config)
    console.print("[green]RAG engine loaded.[/green]")

    # Connect Redis (optional)
    redis_client = connect_redis(config)

    # Single-shot mode
    if args.query:
        result = handle_query(engine, args.query, config, redis_client)
        display_result(result)
        sys.exit(0)

    # Interactive REPL
    console.print(
        Panel(
            "Welcome to the PLC Knowledge Base Chat!\n"
            "Type 'help' for commands, or ask a question about PLCs.",
            title="PLC KB Chat",
            border_style="bright_blue",
        )
    )

    session: PromptSession = PromptSession(history=InMemoryHistory())

    while True:
        try:
            user_input = session.prompt("\n📚 > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("quit", "exit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == "clear":
            os.system("clear" if os.name != "nt" else "cls")
            continue

        if cmd == "help":
            display_help()
            continue

        if cmd == "sources":
            display_sources_detail(_last_result)
            continue

        if user_input.startswith("!web "):
            web_query = user_input[5:].strip()
            if not config.PERPLEXITY_API_KEY:
                console.print("[red]Perplexity API key not set.[/red]")
                continue
            with console.status("[bold]Searching the web..."):
                try:
                    web_result = asyncio.get_event_loop().run_until_complete(
                        perplexity_search(web_query, config)
                    )
                    console.print(
                        Panel(web_result, title="[WEB] Search Result", border_style="yellow")
                    )
                except Exception as e:
                    console.print(f"[red]Web search failed: {e}[/red]")
            continue

        # RAG query
        with console.status("[bold green]Thinking..."):
            result = handle_query(engine, user_input, config, redis_client)
        display_result(result)


if __name__ == "__main__":
    main()
