"""Knowledge Sources API router — §5.14, Sprint 10.

Endpoints:
  GET    /api/knowledge-sources
  POST   /api/knowledge-sources
  GET    /api/knowledge-sources/{source_id}
  PATCH  /api/knowledge-sources/{source_id}
  DELETE /api/knowledge-sources/{source_id}
  POST   /api/knowledge-sources/{source_id}/activate
  POST   /api/knowledge-sources/{source_id}/deactivate
  POST   /api/knowledge-sources/{source_id}/test
  GET    /api/knowledge-sources/{source_id}/stats
  POST   /api/knowledge-sources/search
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from app.api.deps import require_gateway_token
from app.exceptions import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/knowledge-sources",
    tags=["knowledge-sources"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Per-backend connection config schemas (TD-55) ─────────────────────────────

_IDENT_PATTERN = r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$"


class PgVectorConnectionConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    database: str = ""
    user: str = ""
    password: str = ""
    table: str = Field(default="documents", pattern=_IDENT_PATTERN)
    content_col: str = Field(default="content", pattern=_IDENT_PATTERN)
    emb_col: str = Field(default="embedding", pattern=_IDENT_PATTERN)
    meta_cols: list[str] = Field(default_factory=list)

    @classmethod
    def validate_meta_cols(cls, values: Any) -> Any:
        import re
        ident_re = re.compile(_IDENT_PATTERN)
        for col in values.get("meta_cols", []):
            if not ident_re.match(col):
                raise ValueError(f"Invalid SQL identifier in meta_cols: {col!r}")
        return values


class HttpConnectionConfig(BaseModel):
    url: HttpUrl | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    method: str = "POST"
    query_param: str = "query"
    results_path: str = "results"
    content_field: str = "text"
    score_field: str = "score"
    metadata_fields: list[str] = Field(default_factory=list)
    timeout_s: float = 10.0


class FaissConnectionConfig(BaseModel):
    index_path: str
    metadata_path: str | None = None


class ChromaConnectionConfig(BaseModel):
    collection_name: str
    host: str | None = None
    port: int | None = None


_BACKEND_CONFIG_MODELS = {
    "pgvector": PgVectorConnectionConfig,
    "http": HttpConnectionConfig,
    "faiss": FaissConnectionConfig,
    "chroma": ChromaConnectionConfig,
}


def _validate_connection(backend: str, connection: dict[str, Any]) -> None:
    """Validate the connection config dict against the backend's schema."""
    model_cls = _BACKEND_CONFIG_MODELS.get(backend)
    if model_cls is None:
        return
    try:
        model_cls(**connection)
    except Exception as exc:
        raise ValueError(f"Invalid connection config for backend '{backend}': {exc}") from exc


# ── Request / Response bodies ─────────────────────────────────────────────────


class RegisterSourceRequest(BaseModel):
    name: str
    description: str = ""
    backend: Literal["chroma", "pgvector", "faiss", "http"]  # TD-56: validated enum
    query_mode: str = "vector"  # text | vector
    embedding_provider: str | None = None
    auto_recall: bool = False
    priority: int = 0
    max_results: int = 10
    similarity_threshold: float = 0.65
    connection: dict[str, Any] = Field(default_factory=dict)
    allowed_agents: list[str] | None = None


class UpdateSourceRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    auto_recall: bool | None = None
    priority: int | None = None
    max_results: int | None = None
    similarity_threshold: float | None = None
    allowed_agents: list[str] | None = None


class SearchRequest(BaseModel):
    query: str
    source_ids: list[str] | None = None
    agent_id: str | None = None
    top_k: int = 10


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_registry():
    """Return the KnowledgeSourceRegistry or raise 503."""
    try:
        from app.knowledge.sources.registry import get_knowledge_source_registry
        return get_knowledge_source_registry()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _source_to_dict(source) -> dict:
    d = source.model_dump()
    # Expose `source_id` as `id` for API consumers
    d["id"] = d.pop("source_id", None)
    return d


# ── GET /api/knowledge-sources ────────────────────────────────────────────────


@router.get("")
async def list_sources(
    status: str | None = Query(None, description="Filter by status"),
    backend: str | None = Query(None, description="Filter by backend"),
    auto_recall: bool | None = Query(None, description="Filter auto_recall only"),
) -> dict:
    """List registered knowledge sources."""
    registry = _get_registry()
    sources = await registry.list(
        status=status,
        backend=backend,
        auto_recall_only=bool(auto_recall) if auto_recall is not None else False,
    )
    return {"sources": [_source_to_dict(s) for s in sources], "total": len(sources)}


# ── POST /api/knowledge-sources ───────────────────────────────────────────────


@router.post("", status_code=201)
async def register_source(body: RegisterSourceRequest) -> dict:
    """Register a new knowledge source (starts as disabled)."""
    # TD-55: validate connection config against per-backend schema
    try:
        _validate_connection(body.backend, body.connection)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    registry = _get_registry()
    try:
        source = await registry.register(
            name=body.name,
            description=body.description,
            backend=body.backend,
            query_mode=body.query_mode,
            embedding_provider=body.embedding_provider,
            auto_recall=body.auto_recall,
            priority=body.priority,
            max_results=body.max_results,
            similarity_threshold=body.similarity_threshold,
            connection=body.connection,
            allowed_agents=body.allowed_agents,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _source_to_dict(source)


# ── GET /api/knowledge-sources/{source_id} ────────────────────────────────────


@router.get("/{source_id}")
async def get_source(source_id: str) -> dict:
    """Return a single knowledge source by ID."""
    registry = _get_registry()
    try:
        source = await registry.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{source_id}' not found.")
    return _source_to_dict(source)


# ── PATCH /api/knowledge-sources/{source_id} ─────────────────────────────────


@router.patch("/{source_id}")
async def update_source(source_id: str, body: UpdateSourceRequest) -> dict:
    """Update mutable fields on a knowledge source."""
    registry = _get_registry()
    # TD-92: use model_dump(exclude_unset=True) so explicitly-set None values are
    # preserved (e.g. clearing allowed_agents), while unset fields are ignored.
    kwargs = body.model_dump(exclude_unset=True)
    if not kwargs:
        raise HTTPException(status_code=422, detail="No fields to update.")
    try:
        source = await registry.update(source_id, **kwargs)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{source_id}' not found.")
    return _source_to_dict(source)


# ── DELETE /api/knowledge-sources/{source_id} ────────────────────────────────


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str) -> None:
    """Remove a knowledge source permanently."""
    registry = _get_registry()
    try:
        await registry.delete(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{source_id}' not found.")


# ── POST /api/knowledge-sources/{source_id}/activate ─────────────────────────


@router.post("/{source_id}/activate")
async def activate_source(source_id: str) -> dict:
    """Run health-check and activate the source if healthy."""
    registry = _get_registry()
    try:
        source = await registry.activate(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{source_id}' not found.")
    except Exception:
        logger.exception("Knowledge source activation failed for %s", source_id)
        raise HTTPException(status_code=503, detail="Activation failed — check server logs") from None
    return _source_to_dict(source)


# ── POST /api/knowledge-sources/{source_id}/deactivate ───────────────────────


@router.post("/{source_id}/deactivate")
async def deactivate_source(source_id: str) -> dict:
    """Deactivate a knowledge source (status → disabled)."""
    registry = _get_registry()
    try:
        source = await registry.deactivate(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{source_id}' not found.")
    return _source_to_dict(source)


# ── POST /api/knowledge-sources/{source_id}/test ─────────────────────────────


@router.post("/{source_id}/test")
async def test_source(source_id: str) -> dict:
    """Run a health-check on the source without changing its status."""
    registry = _get_registry()
    try:
        adapter = registry.get_adapter(source_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{source_id}' not found or not active.")
    try:
        healthy = await adapter.health_check()
        count = await adapter.count()
    except Exception:
        logger.exception("Knowledge source test failed for %s", source_id)
        return {"healthy": False, "error": "Test failed — check server logs", "count": -1}
    return {"healthy": healthy, "count": count}


# ── GET /api/knowledge-sources/{source_id}/stats ─────────────────────────────


@router.get("/{source_id}/stats")
async def source_stats(source_id: str) -> dict:
    """Return stats (document count, status) for a knowledge source."""
    registry = _get_registry()
    try:
        source = await registry.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Knowledge source '{source_id}' not found.")

    count = -1
    try:
        adapter = registry.get_adapter(source_id)
        count = await adapter.count()
    except (KeyError, Exception):
        pass  # inactive source or adapter error

    return {
        "source_id": source_id,
        "name": source.name,
        "status": source.status,
        "count": count,
        "consecutive_failures": source.consecutive_failures,
        "last_health_check": source.last_health_check,
    }


# ── POST /api/knowledge-sources/search ───────────────────────────────────────


@router.post("/search")
async def search_sources(body: SearchRequest) -> dict:
    """Federated search across one or more knowledge sources."""
    registry = _get_registry()
    try:
        chunks = await registry.search(
            query=body.query,
            source_ids=body.source_ids,
            agent_id=body.agent_id or "",
            top_k=body.top_k,
        )
    except Exception:
        logger.exception("Knowledge source search failed")
        raise HTTPException(status_code=500, detail="Internal error — check server logs") from None
    return {
        "query": body.query,
        "results": [c.model_dump() for c in chunks],
        "total": len(chunks),
    }
