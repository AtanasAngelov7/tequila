"""Sprint 10 — Generic HTTP knowledge source adapter (§5.14).

Uses ``httpx`` (already a project dependency).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.knowledge.sources.adapters.base import KnowledgeSourceAdapter
from app.knowledge.sources.models import KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)


def _get_nested(obj: Any, path: str) -> Any:
    """Resolve a dot-separated key path into a nested dict/list."""
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)]
        else:
            return None
    return obj


class HTTPAdapter(KnowledgeSourceAdapter):
    """Adapter for any HTTP endpoint that accepts a query and returns chunks."""

    async def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[KnowledgeChunk]:
        cfg = self.source.connection
        url: str = cfg.get("url", "")
        method: str = cfg.get("method", "POST").upper()
        headers: dict[str, str] = cfg.get("headers", {})
        query_param: str = cfg.get("query_param", "query")
        results_path: str = cfg.get("results_path", "results")
        content_field: str = cfg.get("content_field", "text")
        score_field: str = cfg.get("score_field", "score")
        metadata_fields: list[str] = cfg.get("metadata_fields", [])
        timeout_s: float = float(cfg.get("timeout_s", 10))

        if not url:
            logger.warning("HTTPAdapter: no URL configured for source %s", self.source.source_id)
            return []

        payload = {query_param: query, "top_k": top_k}

        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                if method == "GET":
                    resp = await client.get(url, params=payload, headers=headers)
                else:
                    resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            raw_results = _get_nested(data, results_path)
            if not isinstance(raw_results, list):
                logger.warning(
                    "HTTPAdapter: results_path %r not a list in response for source %s",
                    results_path, self.source.source_id,
                )
                return []

            chunks: list[KnowledgeChunk] = []
            for item in raw_results[:top_k]:
                if not isinstance(item, dict):
                    continue
                score = float(item.get(score_field, 0.0))
                if score < threshold:
                    continue
                content = item.get(content_field, "")
                meta = {f: item[f] for f in metadata_fields if f in item}
                chunks.append(KnowledgeChunk(
                    source_id=self.source.source_id,
                    content=str(content),
                    score=score,
                    metadata=meta,
                ))
            return sorted(chunks, key=lambda c: c.score, reverse=True)

        except Exception as exc:
            logger.warning("HTTPAdapter search error for source %s: %s", self.source.source_id, exc)
            return []

    async def health_check(self) -> bool:
        cfg = self.source.connection
        url: str = cfg.get("url", "")
        if not url:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                return resp.status_code < 500
        except Exception:
            return False

    async def count(self) -> int:
        """HTTP sources don't expose document count; return -1 as unknown."""
        return -1
