"""Knowledge Vault — markdown note storage with wiki-links (§5.10, Sprint 09).

The vault is the agent's curated, permanent knowledge base.  Notes are stored
as plain markdown files on disk (``data/vault/``) with metadata in SQLite.

Key design decisions:
- Each note has a unique *slug* derived from its title (URL-safe, lowercase).
- File content is stored **only on disk**; the DB stores only metadata + the
  content hash for change detection.
- Wiki-links (``[[note_name]]``) are extracted at write time and stored as
  JSON in the ``wikilinks`` column for fast graph builds.
- ``sync_from_disk()`` reconciles the DB with the filesystem — detects notes
  added/edited/deleted outside the app.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import ConflictError, NotFoundError
from app.paths import vault_dir as _vault_dir

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _slugify(title: str) -> str:
    """Convert *title* to a URL-safe lower-case slug."""
    # Normalise unicode → ASCII
    title = unicodedata.normalize("NFKD", title)
    title = title.encode("ascii", "ignore").decode("ascii")
    title = title.lower().strip()
    # Replace non-alphanumeric runs with a dash
    title = re.sub(r"[^a-z0-9]+", "-", title)
    title = title.strip("-")
    return title or "note"


def _content_hash(content: str) -> str:
    """Return a short SHA-256 hex digest of *content*."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _parse_wikilinks(content: str) -> list[str]:
    """Extract ``[[target]]`` wiki-link targets from markdown *content*."""
    return re.findall(r"\[\[([^\]\|]+?)(?:\|[^\]]+)?\]\]", content)


def _parse_tags(content: str) -> list[str]:
    """Extract ``#tag`` hashtag mentions from *content* (excluding code blocks)."""
    # strip fenced code blocks first
    stripped = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    found = re.findall(r"(?<!\w)#([A-Za-z][A-Za-z0-9_-]*)", stripped)
    return list(dict.fromkeys(found))  # deduplicate, preserve order


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(val: str | None) -> datetime:
    if not val:
        return datetime.now(timezone.utc)
    try:
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        return datetime.fromisoformat(val)
    except ValueError:
        return datetime.now(timezone.utc)


# ── Domain models ─────────────────────────────────────────────────────────────


from pydantic import BaseModel, Field  # noqa: E402


class VaultNote(BaseModel):
    """A single markdown note in the knowledge vault."""

    id: str
    """UUID assigned at creation."""

    title: str
    """Human-readable note title (also used to derive the slug)."""

    slug: str
    """URL/filename-safe version of the title."""

    filename: str
    """Filename within ``vault_dir`` (``<slug>.md``)."""

    content: str = ""
    """Full markdown body — loaded on demand; empty when listing without content."""

    content_hash: str = ""
    """Short hash of the content — used to detect external edits."""

    wikilinks: list[str] = Field(default_factory=list)
    """Targets extracted from ``[[wiki-links]]`` in the content."""

    tags: list[str] = Field(default_factory=list)
    """Hashtag mentions extracted from the content."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """UTC creation time."""

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """UTC last-modified time."""

    @classmethod
    def from_row(cls, row: dict[str, Any], content: str = "") -> "VaultNote":
        """Deserialise a DB row into a VaultNote; optionally include *content*."""
        return cls(
            id=row["id"],
            title=row["title"],
            slug=row["slug"],
            filename=row["filename"],
            content=content,
            content_hash=row.get("content_hash", ""),
            wikilinks=json.loads(row.get("wikilinks", "[]")),
            tags=json.loads(row.get("tags", "[]")),
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
        )


class VaultGraph(BaseModel):
    """Wiki-link graph extracted from all vault notes."""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    """Each entry: ``{id, title, slug}``."""

    edges: list[dict[str, Any]] = Field(default_factory=list)
    """Each entry: ``{source_id, source_slug, target_slug}``."""


class SyncResult(BaseModel):
    """Result of a ``sync_from_disk()`` call."""

    added: int = 0
    """Notes added from disk that weren't in the DB."""

    updated: int = 0
    """Notes whose content changed externally."""

    deleted: int = 0
    """Notes removed from disk whose DB rows were removed."""


# ── VaultStore ────────────────────────────────────────────────────────────────


class VaultStore:
    """Read/write access to the knowledge vault (§5.10)."""

    def __init__(self, db: aiosqlite.Connection, vault_path: Path | None = None) -> None:
        self._db = db
        self._vault_path = vault_path or _vault_dir()
        self._vault_path.mkdir(parents=True, exist_ok=True)
        logger.info("VaultStore initialised.", extra={"vault_dir": str(self._vault_path)})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _note_path(self, filename: str) -> Path:
        return self._vault_path / filename

    async def _unique_slug(self, base_slug: str, exclude_id: str | None = None) -> str:
        """Return *base_slug* (or *base_slug*-N) that is unique in the DB."""
        slug = base_slug
        counter = 1
        while True:
            async with self._db.execute(
                "SELECT id FROM vault_notes WHERE slug = ?", (slug,)
            ) as cur:
                row = await cur.fetchone()
            if row is None or (exclude_id and row["id"] == exclude_id):
                return slug
            slug = f"{base_slug}-{counter}"
            counter += 1

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def create_note(
        self,
        *,
        title: str,
        content: str = "",
        tags: list[str] | None = None,
    ) -> VaultNote:
        """Create a new vault note.

        Raises ``ConflictError`` if a note with the same slug already exists.
        """
        now = _now_iso()
        note_id = str(uuid.uuid4())
        base_slug = _slugify(title)
        slug = await self._unique_slug(base_slug)
        filename = f"{slug}.md"

        # Auto-extract wikilinks and tags
        wikilinks = _parse_wikilinks(content)
        auto_tags = _parse_tags(content)
        combined_tags = list(dict.fromkeys((tags or []) + auto_tags))
        content_h = _content_hash(content)

        # Write file to disk first
        note_path = self._note_path(filename)
        if note_path.exists():
            raise ConflictError(f"Vault file '{filename}' already exists on disk.")
        note_path.write_text(content, encoding="utf-8")

        # Persist metadata
        try:
            async with write_transaction(self._db):
                await self._db.execute(
                    """
                    INSERT INTO vault_notes
                        (id, title, slug, filename, content_hash, wikilinks, tags, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id, title, slug, filename, content_h,
                        json.dumps(wikilinks), json.dumps(combined_tags), now, now,
                    ),
                )
        except Exception:
            note_path.unlink(missing_ok=True)
            raise

        return VaultNote(
            id=note_id, title=title, slug=slug, filename=filename,
            content=content, content_hash=content_h,
            wikilinks=wikilinks, tags=combined_tags,
            created_at=_parse_dt(now), updated_at=_parse_dt(now),
        )

    async def get_note(self, note_id: str, *, include_content: bool = True) -> VaultNote:
        """Return the note with *note_id* or raise ``NotFoundError``."""
        async with self._db.execute(
            "SELECT id, title, slug, filename, content_hash, wikilinks, tags, created_at, updated_at "
            "FROM vault_notes WHERE id = ?",
            (note_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(resource="VaultNote", id=note_id)
        d = row_to_dict(row)
        content = ""
        if include_content:
            note_path = self._note_path(d["filename"])
            content = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        return VaultNote.from_row(d, content=content)

    async def get_note_by_slug(self, slug: str, *, include_content: bool = True) -> VaultNote:
        """Return the note with *slug* or raise ``NotFoundError``."""
        async with self._db.execute(
            "SELECT id, title, slug, filename, content_hash, wikilinks, tags, created_at, updated_at "
            "FROM vault_notes WHERE slug = ?",
            (slug,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(resource="VaultNote", id=slug)
        d = row_to_dict(row)
        content = ""
        if include_content:
            note_path = self._note_path(d["filename"])
            content = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        return VaultNote.from_row(d, content=content)

    async def list_notes(
        self,
        *,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_content: bool = False,
    ) -> list[VaultNote]:
        """Return all vault notes, optionally filtered by *search* (title match)."""
        if search:
            query = (
                "SELECT id, title, slug, filename, content_hash, wikilinks, tags, created_at, updated_at "
                "FROM vault_notes WHERE title LIKE ? "
                "ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            )
            params: tuple = (f"%{search}%", limit, offset)
        else:
            query = (
                "SELECT id, title, slug, filename, content_hash, wikilinks, tags, created_at, updated_at "
                "FROM vault_notes ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            )
            params = (limit, offset)

        async with self._db.execute(query, params) as cur:
            rows = await cur.fetchall()

        notes = []
        for row in rows:
            d = row_to_dict(row)
            content = ""
            if include_content:
                p = self._note_path(d["filename"])
                content = p.read_text(encoding="utf-8") if p.exists() else ""
            notes.append(VaultNote.from_row(d, content=content))
        return notes

    async def update_note(
        self,
        note_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> VaultNote:
        """Update *note_id* fields.  Returns the updated note."""
        note = await self.get_note(note_id)

        new_title = title if title is not None else note.title
        new_content = content if content is not None else note.content
        new_tags_explicit = tags  # None = don't change explicit tags

        now = _now_iso()
        wikilinks = _parse_wikilinks(new_content)
        auto_tags = _parse_tags(new_content)

        if new_tags_explicit is not None:
            combined = list(dict.fromkeys(new_tags_explicit + auto_tags))
        else:
            combined = list(dict.fromkeys(note.tags + auto_tags))

        content_h = _content_hash(new_content)

        # Update file content if content changed
        if new_content != note.content:
            self._note_path(note.filename).write_text(new_content, encoding="utf-8")

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE vault_notes
                   SET title = ?, content_hash = ?, wikilinks = ?, tags = ?, updated_at = ?
                 WHERE id = ?
                """,
                (new_title, content_h, json.dumps(wikilinks), json.dumps(combined), now, note_id),
            )

        return VaultNote(
            id=note.id, title=new_title, slug=note.slug, filename=note.filename,
            content=new_content, content_hash=content_h,
            wikilinks=wikilinks, tags=combined,
            created_at=note.created_at, updated_at=_parse_dt(now),
        )

    async def delete_note(self, note_id: str) -> None:
        """Delete *note_id* from DB and remove the file from disk."""
        note = await self.get_note(note_id, include_content=False)
        async with write_transaction(self._db):
            await self._db.execute("DELETE FROM vault_notes WHERE id = ?", (note_id,))
        self._note_path(note.filename).unlink(missing_ok=True)

    # ── Graph ─────────────────────────────────────────────────────────────────

    async def get_graph(self) -> VaultGraph:
        """Build and return the wiki-link graph for all vault notes."""
        async with self._db.execute(
            "SELECT id, title, slug, wikilinks FROM vault_notes"
        ) as cur:
            rows = await cur.fetchall()

        # Build slug → id/title lookup
        slug_to_meta: dict[str, dict[str, str]] = {}
        for row in rows:
            d = row_to_dict(row)
            slug_to_meta[d["slug"]] = {"id": d["id"], "title": d["title"]}

        nodes = [
            {"id": meta["id"], "title": meta["title"], "slug": slug}
            for slug, meta in slug_to_meta.items()
        ]

        edges: list[dict[str, Any]] = []
        for row in rows:
            d = row_to_dict(row)
            src_id = d["id"]
            src_slug = d["slug"]
            for target_slug in json.loads(d.get("wikilinks", "[]")):
                t_slug = _slugify(target_slug)
                edges.append({"source_id": src_id, "source_slug": src_slug, "target_slug": t_slug})

        return VaultGraph(nodes=nodes, edges=edges)

    # ── Sync ──────────────────────────────────────────────────────────────────

    async def sync_from_disk(self) -> SyncResult:
        """Reconcile DB metadata with files currently on disk.

        - **Added**: ``.md`` files on disk not tracked in DB → import them.
        - **Updated**: tracked files whose content changed (hash mismatch) → re-index.
        - **Deleted**: DB rows whose file no longer exists on disk → remove row.

        Returns a ``SyncResult`` summarising changes made.
        """
        result = SyncResult()

        # ── Load current DB state ─────────────────────────────────────────────
        async with self._db.execute(
            "SELECT id, title, slug, filename, content_hash FROM vault_notes"
        ) as cur:
            rows = await cur.fetchall()

        db_by_filename: dict[str, dict[str, Any]] = {
            row_to_dict(r)["filename"]: row_to_dict(r) for r in rows
        }

        # ── Discover fs files ─────────────────────────────────────────────────
        fs_files: set[str] = {
            p.name for p in self._vault_path.glob("*.md") if p.is_file()
        }

        now = _now_iso()

        # Added or updated
        for filename in fs_files:
            path = self._note_path(filename)
            content = path.read_text(encoding="utf-8")
            h = _content_hash(content)

            if filename not in db_by_filename:
                # New file — import
                note_id = str(uuid.uuid4())
                title = path.stem.replace("-", " ").replace("_", " ").title()
                slug = _slugify(title)
                slug = await self._unique_slug(slug)
                wikilinks = _parse_wikilinks(content)
                auto_tags = _parse_tags(content)
                async with write_transaction(self._db):
                    await self._db.execute(
                        """
                        INSERT INTO vault_notes
                            (id, title, slug, filename, content_hash, wikilinks, tags, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (note_id, title, slug, filename, h,
                         json.dumps(wikilinks), json.dumps(auto_tags), now, now),
                    )
                result.added += 1
            else:
                row = db_by_filename[filename]
                if row["content_hash"] != h:
                    # Content changed externally
                    wikilinks = _parse_wikilinks(content)
                    auto_tags = _parse_tags(content)
                    async with write_transaction(self._db):
                        await self._db.execute(
                            """
                            UPDATE vault_notes
                               SET content_hash = ?, wikilinks = ?, tags = ?, updated_at = ?
                             WHERE id = ?
                            """,
                            (h, json.dumps(wikilinks), json.dumps(auto_tags), now, row["id"]),
                        )
                    result.updated += 1

        # Deleted
        for filename, row in db_by_filename.items():
            if filename not in fs_files:
                async with write_transaction(self._db):
                    await self._db.execute("DELETE FROM vault_notes WHERE id = ?", (row["id"],))
                result.deleted += 1

        if result.added or result.updated or result.deleted:
            logger.info(
                "Vault sync completed.",
                extra={"added": result.added, "updated": result.updated, "deleted": result.deleted},
            )
        return result


# ── Module-level singleton ────────────────────────────────────────────────────

_vault_store: VaultStore | None = None


def init_vault_store(
    db: aiosqlite.Connection, vault_path: Path | None = None
) -> VaultStore:
    """Initialise and register the global VaultStore singleton."""
    global _vault_store  # noqa: PLW0603
    _vault_store = VaultStore(db, vault_path=vault_path)
    return _vault_store


def get_vault_store() -> VaultStore:
    """Return the global VaultStore singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _vault_store is None:
        raise RuntimeError("VaultStore not initialised.  Check app lifespan.")
    return _vault_store
