"""Vector index of Cube metadata: CubeSemanticLoader -> embeddings -> find members relevant to the question."""
from __future__ import annotations

import logging
import os
import threading
import time

from langchain.embeddings import init_embeddings
from langchain_community.document_loaders import CubeSemanticLoader
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore

import cube_client

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "openai:text-embedding-3-small"  # override via env EMBEDDING_MODEL
INDEX_TTL_S = int(os.getenv("SEMANTIC_INDEX_TTL_S", "3600"))
INDEX_USER = "agent"  # shared index; per-user permissions are still enforced by Cube on /load

_lock = threading.Lock()
_index: dict = {"at": 0.0, "store": None}


def _load_docs() -> list[Document]:
    loader = CubeSemanticLoader(
        cube_api_url=cube_client.CUBE_API_URL,
        cube_api_token=cube_client.make_token(INDEX_USER),
        load_dimension_values=False,  # lookup_values tool already exists; avoid calling /load per dimension
    )
    docs = loader.load()
    views = [d for d in docs if d.metadata["cube_data_obj_type"] == "view"]
    return views or docs  # fall back to cubes if there are no views yet


def _get_store() -> InMemoryVectorStore:
    with _lock:  # Streamlit runs multiple threads; avoid building the index concurrently
        if _index["store"] is None or time.time() - _index["at"] > INDEX_TTL_S:
            docs = _load_docs()
            embeddings = init_embeddings(os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL))
            _index.update(at=time.time(), store=InMemoryVectorStore.from_documents(docs, embeddings))
            logger.info("semantic index built: %d members", len(docs))
        return _index["store"]


def search(query: str, k: int) -> list[Document]:
    return _get_store().similarity_search(query, k=k)


def format_docs(docs: list[Document]) -> str:
    """Group by view so the LLM knows which member belongs to which view."""
    by_view: dict[str, list[Document]] = {}
    for d in docs:
        by_view.setdefault(d.metadata["table_name"], []).append(d)
    lines: list[str] = []
    for view, items in by_view.items():
        lines.append(f"VIEW {view}")
        lines.extend(
            f"  - [{d.metadata['column_member_type']}/{d.metadata['column_data_type']}] "
            f"{d.metadata['column_name']}: {d.page_content}"
            for d in items
        )
    return "\n".join(lines)
