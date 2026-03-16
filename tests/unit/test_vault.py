"""Sprint 09 — Unit tests for VaultStore (§5.10)."""
from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
async def vault_store(migrated_db, tmp_path):
    """VaultStore backed by a temp DB and temp vault directory."""
    from app.knowledge.vault import init_vault_store, get_vault_store
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    init_vault_store(migrated_db, vault_path=vault_path)
    return get_vault_store()


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_note_persists_to_disk(vault_store, tmp_path):
    """Creating a note writes a .md file to vault_dir."""
    note = await vault_store.create_note(title="Hello World", content="Some content here.")
    file_path = vault_store._vault_path / note.filename
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "Some content here."


async def test_create_note_parses_wikilinks(vault_store):
    """Wikilinks in content are extracted and stored."""
    note = await vault_store.create_note(
        title="Linked Note",
        content="See [[another-note]] and [[third-note]] for details.",
    )
    assert "another-note" in note.wikilinks
    assert "third-note" in note.wikilinks


async def test_create_note_parses_hashtags(vault_store):
    """Hashtags in content are extracted as tags."""
    note = await vault_store.create_note(
        title="Tagged Note",
        content="Working on #python and #asyncio today.",
    )
    assert "python" in note.tags
    assert "asyncio" in note.tags


async def test_create_note_slug_from_title(vault_store):
    """Slug is derived from the title."""
    note = await vault_store.create_note(title="My Great Note", content="")
    assert note.slug == "my-great-note"
    assert note.filename == "my-great-note.md"


async def test_create_note_unique_slug(vault_store):
    """Second note with same title gets a disambiguating suffix."""
    note1 = await vault_store.create_note(title="Duplicate", content="first")
    note2 = await vault_store.create_note(title="Duplicate", content="second")
    assert note1.slug == "duplicate"
    assert note2.slug == "duplicate-1"


# ── Read ──────────────────────────────────────────────────────────────────────


async def test_get_note_returns_content(vault_store):
    """get_note includes the file content."""
    note = await vault_store.create_note(title="Readable", content="Hello, vault!")
    fetched = await vault_store.get_note(note.id)
    assert fetched.content == "Hello, vault!"
    assert fetched.id == note.id


async def test_get_note_not_found_raises(vault_store):
    """get_note for unknown id raises NotFoundError."""
    from app.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        await vault_store.get_note("nonexistent-id")


async def test_get_note_by_slug(vault_store):
    """get_note_by_slug returns the correct note."""
    note = await vault_store.create_note(title="Slugged Note", content="slug content")
    fetched = await vault_store.get_note_by_slug(note.slug)
    assert fetched.id == note.id


async def test_list_notes_returns_all(vault_store):
    """list_notes returns all created notes."""
    await vault_store.create_note(title="Alpha", content="a")
    await vault_store.create_note(title="Beta", content="b")
    await vault_store.create_note(title="Gamma", content="c")
    notes = await vault_store.list_notes()
    assert len(notes) == 3


async def test_list_notes_search_filter(vault_store):
    """list_notes with search only returns title-matching notes."""
    await vault_store.create_note(title="Python Guide", content="")
    await vault_store.create_note(title="JavaScript Guide", content="")
    await vault_store.create_note(title="Async Tips", content="")
    results = await vault_store.list_notes(search="Guide")
    assert len(results) == 2
    titles = {n.title for n in results}
    assert "Python Guide" in titles
    assert "JavaScript Guide" in titles


# ── Update ────────────────────────────────────────────────────────────────────


async def test_update_note_changes_content(vault_store):
    """Updating content rewrites the disk file."""
    note = await vault_store.create_note(title="Updatable", content="original")
    updated = await vault_store.update_note(note.id, content="revised content")
    assert updated.content == "revised content"
    # Check file on disk
    assert (vault_store._vault_path / note.filename).read_text(encoding="utf-8") == "revised content"


async def test_update_note_rewrites_wikilinks(vault_store):
    """Updating content re-parses wikilinks."""
    note = await vault_store.create_note(title="Link Test", content="See [[old-link]]")
    updated = await vault_store.update_note(note.id, content="See [[new-link]] and [[another]]")
    assert "new-link" in updated.wikilinks
    assert "another" in updated.wikilinks
    assert "old-link" not in updated.wikilinks


# ── Delete ────────────────────────────────────────────────────────────────────


async def test_delete_note_removes_file(vault_store):
    """Deleting a note removes the disk file."""
    note = await vault_store.create_note(title="Deletable", content="bye")
    file_path = vault_store._vault_path / note.filename
    assert file_path.exists()
    await vault_store.delete_note(note.id)
    assert not file_path.exists()


async def test_delete_note_removes_from_db(vault_store):
    """Deleting a note means get_note raises NotFoundError."""
    from app.exceptions import NotFoundError
    note = await vault_store.create_note(title="Gone", content="")
    await vault_store.delete_note(note.id)
    with pytest.raises(NotFoundError):
        await vault_store.get_note(note.id)


# ── Graph ─────────────────────────────────────────────────────────────────────


async def test_graph_contains_nodes(vault_store):
    """Graph nodes include all created notes."""
    await vault_store.create_note(title="Node A", content="")
    await vault_store.create_note(title="Node B", content="")
    graph = await vault_store.get_graph()
    assert len(graph.nodes) == 2
    slugs = {n["slug"] for n in graph.nodes}
    assert "node-a" in slugs
    assert "node-b" in slugs


async def test_graph_has_edges_from_wikilinks(vault_store):
    """Notes that link to other notes create graph edges."""
    await vault_store.create_note(title="Source", content="Links to [[target-note]]")
    await vault_store.create_note(title="Target Note", content="")
    graph = await vault_store.get_graph()
    assert len(graph.edges) >= 1
    edge = graph.edges[0]
    assert "source_id" in edge
    assert edge["target_slug"] == "target-note"


# ── Sync ──────────────────────────────────────────────────────────────────────


async def test_sync_detects_external_addition(vault_store):
    """sync_from_disk imports .md files written externally."""
    # Write a file directly — bypasses VaultStore.create_note
    (vault_store._vault_path / "external-note.md").write_text("External content", encoding="utf-8")
    result = await vault_store.sync_from_disk()
    assert result.added == 1


async def test_sync_detects_external_deletion(vault_store):
    """sync_from_disk removes DB row when file is deleted externally."""
    note = await vault_store.create_note(title="Temp Note", content="hello")
    # Delete the file directly
    (vault_store._vault_path / note.filename).unlink()
    result = await vault_store.sync_from_disk()
    assert result.deleted == 1


async def test_sync_detects_external_edit(vault_store):
    """sync_from_disk marks notes whose content changed externally."""
    note = await vault_store.create_note(title="Editable", content="original")
    # Modify the file directly
    (vault_store._vault_path / note.filename).write_text("modified externally", encoding="utf-8")
    result = await vault_store.sync_from_disk()
    assert result.updated == 1
