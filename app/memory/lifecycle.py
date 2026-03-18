"""Memory lifecycle management — decay, consolidation, archival (§5.8, Sprint 11).

Runs periodic maintenance passes over the memory store:

1. **Decay**  — recalculate ``decay_score`` for every active memory.
   Formula: ``score = max(floor, 0.5 ** (days_since_access / half_life_days))``
   When ``access_resets_decay=True`` (default), recent access restores the score
   toward 1.0.  Memories with ``always_recall=True`` are immune.

2. **Consolidation** — weekly (or on-demand):
   a. Merge near-duplicate pairs (embedding similarity ≥ ``merge_threshold``).
   b. Summarise entity clusters with > ``summarize_threshold`` memories.
   c. Archive memories whose ``decay_score`` has fallen below ``archive_threshold``.
   d. Expire stale tasks (``memory_type='task'`` past ``expires_at``).
   e. Report orphan memories (no entity links, not accessed in 60+ days).

All significant mutations are recorded via ``MemoryAuditLog``.

Singletons:
- ``init_lifecycle_manager(…) → MemoryLifecycleManager``
- ``get_lifecycle_manager() → MemoryLifecycleManager``
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Store Protocols (TD-110) ────────────────────────────────────────


@runtime_checkable
class MemoryStoreProtocol(Protocol):
    """Minimal interface that MemoryLifecycleManager requires from the memory store."""

    async def list(self, **kwargs: Any) -> list[Any]: ...
    async def get(self, memory_id: str) -> Any: ...
    async def update(self, memory_id: str, **kwargs: Any) -> Any: ...
    async def link_entity(self, memory_id: str, entity_id: str) -> None: ...
    async def soft_delete(self, memory_id: str) -> Any: ...


@runtime_checkable
class EntityStoreProtocol(Protocol):
    """Minimal interface that MemoryLifecycleManager requires from the entity store."""

    async def list(self, **kwargs: Any) -> list[Any]: ...
    async def get(self, entity_id: str) -> Any: ...

# ── Configuration models ──────────────────────────────────────────────────────


class MemoryDecayConfig(BaseModel):
    """Parameters governing the exponential decay of memory recall weight (§5.8)."""

    enabled: bool = True
    """Whether decay recalculation is active."""

    half_life_days: float = 90.0
    """Number of days until an un-accessed memory's score halves."""

    floor: float = 0.1
    """Minimum decay_score — memories never fall below this."""

    access_resets_decay: bool = True
    """Reset the decay clock whenever a memory is accessed."""

    always_recall_immune: bool = True
    """Skip decay recalculation for ``always_recall=True`` memories."""

    task_post_expiry_decay_days: float = 7.0
    """Days after a task's ``expires_at`` before it is archived."""


class ConsolidationConfig(BaseModel):
    """Parameters governing the weekly consolidation pass (§5.8)."""

    enabled: bool = True
    """Whether consolidation is active."""

    merge_threshold: float = 0.92
    """Cosine similarity threshold above which two memories are merged."""

    summarize_threshold: int = 10
    """Minimum number of memories per entity cluster before summarisation."""

    archive_threshold: float = 0.15
    """Memories with ``decay_score < archive_threshold`` are archived."""

    orphan_report_after_days: int = 60
    """Memories with no entity link and no access in this many days are flagged."""

    batch_size: int = 50
    """Number of memories processed per DB write batch (§20.5)."""


# ── The manager ───────────────────────────────────────────────────────────────


class MemoryLifecycleManager:
    """Runs memory maintenance passes (§5.8).

    This class is *deliberately sync-capable* for scheduler use; every method
    is a coroutine so it can also be ``await``-ed from async contexts.

    Args:
        memory_store:  ``MemoryStore`` singleton.
        entity_store:  ``EntityStore`` singleton.
        audit_log:     ``MemoryAuditLog`` singleton (optional — falls back to
                       a no-op if not provided).
        decay_cfg:     Decay configuration (defaults to spec defaults).
        consol_cfg:    Consolidation configuration (defaults to spec defaults).
    """

    def __init__(
        self,
        memory_store: MemoryStoreProtocol,
        entity_store: EntityStoreProtocol,
        audit_log: Any | None = None,
        *,
        decay_cfg: MemoryDecayConfig | None = None,
        consol_cfg: ConsolidationConfig | None = None,
    ) -> None:
        self._mem = memory_store
        self._ent = entity_store
        self._audit = audit_log
        self.decay_cfg = decay_cfg or MemoryDecayConfig()
        self.consol_cfg = consol_cfg or ConsolidationConfig()
        self._run_lock: asyncio.Lock = asyncio.Lock()  # TD-109: prevent concurrent lifecycle passes

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_decay(
        last_accessed: datetime,
        half_life_days: float,
        floor: float,
        *,
        now: datetime | None = None,
    ) -> float:
        """Compute the decay score using the spec formula.

        ``score = max(floor, 0.5 ** (days_since_access / half_life_days))``
        """
        # TD-337: Guard against zero half-life to prevent ZeroDivisionError
        if half_life_days <= 0:
            return 1.0  # no decay when half-life is undefined/zero
        _now = now or datetime.now(timezone.utc)
        # Ensure timezone-aware comparison
        if last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)
        days = (_now - last_accessed).total_seconds() / 86_400
        score = 0.5 ** (days / half_life_days)
        return max(floor, score)

    async def _audit_log(self, **kwargs: Any) -> None:
        """Fire-and-forget audit log entry, ignoring errors."""
        if self._audit is None:
            return
        try:
            await self._audit.log(**kwargs)
        except Exception:  # noqa: BLE001
            logger.warning("Lifecycle audit event failed", exc_info=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_decay(self) -> dict[str, int]:
        """Recalculate decay_score for all active memories.

        Processes memories in batches of ``consol_cfg.batch_size`` (§20.5).

        Returns:
            ``{"processed": N, "updated": M, "skipped": K}``
        """
        if not self.decay_cfg.enabled:
            return {"processed": 0, "updated": 0, "skipped": 0}

        cfg = self.decay_cfg
        now = datetime.now(timezone.utc)
        processed = 0
        updated = 0
        skipped = 0
        last_id = ""  # TD-293: cursor-based pagination (matches run_archive pattern)
        batch = self.consol_cfg.batch_size

        while True:
            memories = await self._mem.list(
                status="active",
                limit=batch,
                after_id=last_id,
            )
            if not memories:
                break
            batch_updates: list[tuple[str, float]] = []
            for mem in memories:
                processed += 1
                if cfg.always_recall_immune and mem.always_recall:
                    skipped += 1
                    continue
                new_score = self._compute_decay(
                    mem.last_accessed,
                    cfg.half_life_days,
                    cfg.floor,
                    now=now,
                )
                if abs(new_score - mem.decay_score) < 0.001:
                    skipped += 1
                    continue
                batch_updates.append((mem.id, new_score))
                await self._audit_log(
                    event_type="decay_recalculated",
                    memory_id=mem.id,
                    actor="system",
                    reason=f"score changed from {mem.decay_score:.4f} to {new_score:.4f}",
                    metadata={"old_score": mem.decay_score, "new_score": new_score},
                )

            # TD-365: Apply all decay updates in one executemany per batch
            if batch_updates:
                n = await self._mem.update_decay_scores_bulk(batch_updates)
                updated += n
            last_id = memories[-1].id

        logger.info(
            "Decay pass: processed=%d updated=%d skipped=%d",
            processed, updated, skipped,
        )
        return {"processed": processed, "updated": updated, "skipped": skipped}

    async def run_archive(self) -> dict[str, int]:
        """Archive memories whose decay_score has fallen below ``archive_threshold``.

        Memories with ``always_recall=True`` or ``pinned=True`` are immune.

        Returns:
            ``{"examined": N, "archived": M}``
        """
        if not self.consol_cfg.enabled:
            return {"examined": 0, "archived": 0}

        threshold = self.consol_cfg.archive_threshold
        batch = self.consol_cfg.batch_size
        examined = 0
        archived = 0
        last_id = ""  # TD-65: cursor-based pagination to avoid skipping on mutations

        while True:
            memories = await self._mem.list(
                status="active",
                limit=batch,
                after_id=last_id,
            )
            if not memories:
                break
            for mem in memories:
                examined += 1
                if mem.always_recall or mem.pinned:
                    continue
                if mem.decay_score >= threshold:
                    continue
                old_content = mem.content
                await self._mem.update(mem.id, status="archived")
                await self._audit_log(
                    event_type="archived",
                    memory_id=mem.id,
                    actor="consolidation",
                    old_content=old_content,
                    reason=f"decay_score {mem.decay_score:.4f} < threshold {threshold}",
                )
                archived += 1
            last_id = memories[-1].id

        logger.info("Archive pass: examined=%d archived=%d", examined, archived)
        return {"examined": examined, "archived": archived}

    async def run_expire_tasks(self) -> dict[str, int]:
        """Expire task-type memories that have passed their ``expires_at`` date.

        After ``task_post_expiry_decay_days`` grace period, the task is archived.

        Returns:
            ``{"examined": N, "expired": M}``
        """
        now = datetime.now(timezone.utc)
        grace = timedelta(days=self.decay_cfg.task_post_expiry_decay_days)
        batch = self.consol_cfg.batch_size
        examined = 0
        expired = 0
        last_id = ""  # TD-65: cursor-based pagination

        while True:
            memories = await self._mem.list(
                memory_type="task",
                status="active",
                limit=batch,
                after_id=last_id,
            )
            if not memories:
                break
            for mem in memories:
                examined += 1
                if mem.expires_at is None:
                    continue
                expiry = mem.expires_at
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if now < expiry + grace:
                    continue
                await self._mem.update(mem.id, status="archived")
                await self._audit_log(
                    event_type="archived",
                    memory_id=mem.id,
                    actor="system",
                    old_content=mem.content,
                    reason=f"task expired at {mem.expires_at.isoformat()}",
                )
                expired += 1
            last_id = memories[-1].id

        logger.info("Expire-tasks pass: examined=%d expired=%d", examined, expired)
        return {"examined": examined, "expired": expired}

    async def run_merge(self) -> dict[str, int]:
        """Merge near-duplicate memories (embedding similarity ≥ ``merge_threshold``).

        For each active memory, the ``EmbeddingStore`` is queried for similar
        memories.  When a pair exceeds the threshold, the newer / lower-confidence
        memory is soft-deleted and its entity links are transferred to the survivor.

        Returns:
            ``{"examined": N, "merged": M}``
        """
        if not self.consol_cfg.enabled:
            return {"examined": 0, "merged": 0}

        try:
            from app.knowledge.embeddings import get_embedding_store
            emb = get_embedding_store()
        except RuntimeError:
            logger.info("Lifecycle merge: EmbeddingStore not available, skipping.")
            return {"examined": 0, "merged": 0}

        threshold = self.consol_cfg.merge_threshold
        batch = self.consol_cfg.batch_size
        examined = 0
        merged = 0
        merged_ids: set[str] = set()
        last_id = ""  # TD-65: cursor-based pagination
        consecutive_embedding_failures = 0  # TD-103: track embedding unavailability

        while True:
            memories = await self._mem.list(
                status="active",
                limit=batch,
                after_id=last_id,
            )
            if not memories:
                break
            for mem in memories:
                if mem.id in merged_ids:
                    continue
                examined += 1
                try:
                    hits = await emb.search(
                        mem.content,
                        source_types=["memory"],
                        limit=5,
                        threshold=threshold,
                    )
                    consecutive_embedding_failures = 0
                except Exception:  # noqa: BLE001
                    consecutive_embedding_failures += 1
                    logger.warning(
                        "Embedding similarity failed (consecutive: %d) for memory %s",
                        consecutive_embedding_failures, mem.id, exc_info=True,
                    )
                    if consecutive_embedding_failures >= 3:
                        logger.error("Aborting merge pass — embedding store unavailable")
                        break
                    continue
                for hit in hits:
                    if hit.source_id == mem.id or hit.source_id in merged_ids:
                        continue
                    # Decide which to keep: favour always_recall, then pinned,
                    # then higher confidence, then older (created_at).
                    try:
                        other = await self._mem.get(hit.source_id)
                    except Exception:  # noqa: BLE001
                        continue
                    # Survivor = mem (already loaded); victim = other.
                    if other.always_recall and not mem.always_recall:
                        survivor, victim = other, mem
                    elif mem.always_recall and not other.always_recall:
                        survivor, victim = mem, other
                    elif other.confidence > mem.confidence:
                        survivor, victim = other, mem
                    else:
                        survivor, victim = mem, other

                    # Transfer entity links from victim → survivor
                    victim_entity_ids = json_list(victim.entity_ids)
                    for eid in victim_entity_ids:
                        try:
                            await self._mem.link_entity(survivor.id, eid)
                        except Exception:  # noqa: BLE001
                            pass

                    # Soft-delete victim
                    await self._mem.soft_delete(victim.id)
                    merged_ids.add(victim.id)

                    await self._audit_log(
                        event_type="merged",
                        memory_id=victim.id,
                        actor="consolidation",
                        old_content=victim.content,
                        new_content=survivor.content,
                        reason=f"merged into {survivor.id} (similarity={hit.similarity:.4f})",
                        metadata={
                            "survivor_id": survivor.id,
                            "similarity": hit.similarity,
                        },
                    )
                    merged += 1
                    # Ensure we don't process the victim later
                    break
            last_id = memories[-1].id

        logger.info("Merge pass: examined=%d merged=%d", examined, merged)
        return {"examined": examined, "merged": merged}

    async def run_orphan_report(self) -> dict[str, Any]:
        """Identify memories that have no entity links and have not been accessed recently.

        Returns:
            ``{"orphan_ids": [...], "count": N}``
        """
        cutoff_days = self.consol_cfg.orphan_report_after_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
        batch = self.consol_cfg.batch_size
        orphans: list[str] = []
        last_id: str | None = None

        while True:
            memories = await self._mem.list(
                status="active",
                limit=batch,
                after_id=last_id,
            )
            if not memories:
                break
            for mem in memories:
                last_id = mem.id
                if mem.always_recall or mem.pinned:
                    continue
                # No entity links?
                entity_ids = json_list(mem.entity_ids)
                if entity_ids:
                    continue
                # Not accessed recently?
                last_acc = mem.last_accessed
                if last_acc.tzinfo is None:
                    last_acc = last_acc.replace(tzinfo=timezone.utc)
                if last_acc >= cutoff:
                    continue
                orphans.append(mem.id)

        logger.info("Orphan report: %d orphan memories found.", len(orphans))
        return {"orphan_ids": orphans, "count": len(orphans)}

    async def run_all(self) -> dict[str, Any]:
        """Run the full lifecycle pass in order.

        If a pass is already in progress (concurrent scheduler tick), the call
        returns immediately with ``{"skipped": True}`` rather than running two
        passes in parallel (TD-109).

        Order:
        1. decay
        2. expire_tasks
        3. archive
        4. merge
        5. orphan_report

        Returns a dict of all sub-pass results.
        """
        if self._run_lock.locked():
            logger.info("MemoryLifecycleManager: lifecycle pass already in progress, skipping.")
            return {"skipped": True, "reason": "already_running"}
        async with self._run_lock:
            logger.info("MemoryLifecycleManager: starting full run.")
            results: dict[str, Any] = {}
            results["decay"] = await self.run_decay()
            results["expire_tasks"] = await self.run_expire_tasks()
            results["archive"] = await self.run_archive()
            results["merge"] = await self.run_merge()
            results["orphan_report"] = await self.run_orphan_report()
            logger.info("MemoryLifecycleManager: full run complete — %s", results)
            return results


# ── Helpers ───────────────────────────────────────────────────────────────────


def json_list(value: Any) -> list[str]:
    """Safely decode a JSON-encoded list of strings from DB rows."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        import json as _json
        try:
            parsed = _json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (ValueError, TypeError):
            pass
    return []


# ── Module-level singleton ────────────────────────────────────────────────────

_lifecycle_manager: MemoryLifecycleManager | None = None


def init_lifecycle_manager(
    memory_store: Any,
    entity_store: Any,
    audit_log: Any | None = None,
    *,
    decay_cfg: MemoryDecayConfig | None = None,
    consol_cfg: ConsolidationConfig | None = None,
) -> MemoryLifecycleManager:
    """Initialise and register the global MemoryLifecycleManager singleton."""
    global _lifecycle_manager  # noqa: PLW0603
    _lifecycle_manager = MemoryLifecycleManager(
        memory_store=memory_store,
        entity_store=entity_store,
        audit_log=audit_log,
        decay_cfg=decay_cfg,
        consol_cfg=consol_cfg,
    )
    logger.info("MemoryLifecycleManager initialised.")
    return _lifecycle_manager


def get_lifecycle_manager() -> MemoryLifecycleManager:
    """Return the global MemoryLifecycleManager singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _lifecycle_manager is None:
        raise RuntimeError(
            "MemoryLifecycleManager not initialised.  Call init_lifecycle_manager() first."
        )
    return _lifecycle_manager
