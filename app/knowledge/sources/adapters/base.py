"""Sprint 10 — KnowledgeSourceAdapter ABC (§5.14)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.knowledge.sources.models import KnowledgeChunk, KnowledgeSource


class KnowledgeSourceAdapter(ABC):
    """Base class for knowledge source backend adapters."""

    def __init__(self, source: KnowledgeSource) -> None:
        self.source = source

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[KnowledgeChunk]:
        """Search the knowledge source. Returns ranked chunks."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Test connectivity to the backend. Returns True if healthy."""

    @abstractmethod
    async def count(self) -> int:
        """Return the approximate number of documents/chunks in the source."""
    async def deactivate(self) -> None:
        """Release any resources held by this adapter (e.g. connection pools).

        Default implementation is a no-op.  Override in adapters that hold
        long-lived resources (TD-94).
        """