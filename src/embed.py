"""Load chunks from data/processed/ → embed → upsert into Qdrant."""

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console

from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from src.config import Config, get_config

console = Console()


def get_qdrant_client(config: Config) -> QdrantClient:
    """Create Qdrant client based on config (local file or remote URL)."""
    if config.USE_LOCAL_QDRANT:
        return QdrantClient(path=str(config.QDRANT_LOCAL_PATH))
    return QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY or None)


def load_nodes_from_processed(processed_dir: Path) -> list[TextNode]:
    """Load serialized nodes from data/processed/nodes.json."""
    nodes_path = processed_dir / "nodes.json"
    if not nodes_path.exists():
        console.print(
            f"[red]No nodes.json found at {nodes_path}. "
            "Run 'python -m src.ingest' first.[/red]"
        )
        sys.exit(1)

    raw = json.loads(nodes_path.read_text())
    nodes = []
    for item in raw:
        node = TextNode.from_dict(item)
        nodes.append(node)
    return nodes


def get_existing_skus(client: QdrantClient, collection_name: str) -> set[str]:
    """Get set of SKUs already in the Qdrant collection."""
    try:
        # Scroll through collection to find existing SKUs
        result = client.scroll(
            collection_name=collection_name,
            limit=1,
            with_payload=True,
        )
        if not result[0]:
            return set()

        # Get unique SKUs from a sample scroll
        skus = set()
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=collection_name,
                limit=100,
                offset=offset,
                with_payload=["sku"],
            )
            for point in points:
                sku = point.payload.get("sku", "")
                if sku:
                    skus.add(sku)
            if offset is None:
                break
        return skus
    except Exception:
        return set()


def build_index(config: Config, force: bool = False) -> VectorStoreIndex:
    """Build or update the Qdrant vector index from processed nodes."""
    client = get_qdrant_client(config)

    if force:
        try:
            client.delete_collection(config.QDRANT_COLLECTION)
            console.print("[yellow]Deleted existing collection.[/yellow]")
        except Exception:
            pass

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=config.QDRANT_COLLECTION,
    )

    Settings.embed_model = OpenAIEmbedding(
        model=config.EMBED_MODEL,
        api_key=config.OPENAI_API_KEY,
        dimensions=config.EMBED_DIMENSIONS,
    )

    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    nodes = load_nodes_from_processed(config.PROCESSED_DIR)

    if not force:
        existing_skus = get_existing_skus(client, config.QDRANT_COLLECTION)
        if existing_skus:
            before = len(nodes)
            nodes = [n for n in nodes if n.metadata.get("sku") not in existing_skus]
            skipped = before - len(nodes)
            if skipped:
                console.print(
                    f"[yellow]Skipping {skipped} nodes from already-indexed SKUs: "
                    f"{sorted(existing_skus)}[/yellow]"
                )

    if not nodes:
        console.print("[green]All nodes already indexed. Nothing to do.[/green]")
        index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )
        return index

    console.print(f"[bold]Embedding {len(nodes)} nodes...[/bold]")
    index = VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        show_progress=True,
    )
    return index


def main():
    parser = argparse.ArgumentParser(description="Embed chunks into Qdrant")
    parser.add_argument("--force", action="store_true", help="Re-embed all (delete collection first)")
    args = parser.parse_args()

    config = get_config()

    if not config.OPENAI_API_KEY:
        console.print("[red][ERROR] OPENAI_API_KEY is not set. Add it to your .env file.[/red]")
        sys.exit(1)

    with console.status("[bold green]Building index..."):
        index = build_index(config, force=args.force)

    console.print("[green]Embedding complete![/green]")


if __name__ == "__main__":
    main()
