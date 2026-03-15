"""Sprint 06 — Filesystem built-in tools (§16.1).

Provides four tools:
- ``fs_list_dir``   — list directory contents (read_only)
- ``fs_read_file``  — read file text with optional line range (read_only)
- ``fs_write_file`` — create / overwrite / append file (side_effect)
- ``fs_search``     — glob-pattern search for files (read_only)

Path safety
-----------
All paths are validated through ``PathPolicy``:
- ``..`` traversal components are rejected outright.
- Absolute paths are resolved and must fall within at least one of the
  configured ``allowed_roots``.  An empty ``allowed_roots`` list disables
  root checking (permissive mode — only traversal checks apply).
- Default roots: ``[Path.home()]``.
"""
from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

from app.tools.registry import tool

logger = logging.getLogger(__name__)

# ── Path policy ────────────────────────────────────────────────────────────────


class PathPolicy:
    """Validate and resolve file paths against security rules.

    Parameters
    ----------
    allowed_roots:
        List of absolute Path objects.  A resolved path must be a descendant
        of at least one root.  If the list is empty, root checking is skipped.
    """

    def __init__(self, allowed_roots: list[Path] | None = None) -> None:
        if allowed_roots is None:
            self._roots: list[Path] = [Path.home()]
        else:
            self._roots = [r.resolve() for r in allowed_roots]

    def resolve_safe(self, raw: str) -> Path:
        """Return a resolved absolute ``Path`` for *raw* or raise ``PermissionError``.

        Raises
        ------
        PermissionError
            If ``..`` traversal is detected in the raw path, or the resolved
            path lies outside all allowed roots (when roots are configured).
        """
        # Block explicit traversal before any resolution
        if ".." in Path(raw).parts:
            raise PermissionError(f"Path traversal not allowed: {raw!r}")

        resolved = Path(raw).expanduser().resolve()

        if self._roots:
            if not any(
                resolved == root or resolved.is_relative_to(root)
                for root in self._roots
            ):
                roots_str = ", ".join(str(r) for r in self._roots)
                raise PermissionError(
                    f"Path {resolved!r} is outside allowed roots [{roots_str}]"
                )

        return resolved


# Module-level default policy (used by tools unless overridden in tests)
_default_policy = PathPolicy()


def _get_policy() -> PathPolicy:
    return _default_policy


def set_path_policy(policy: PathPolicy) -> None:
    """Replace the module-level ``PathPolicy`` (useful in tests)."""
    global _default_policy  # noqa: PLW0603
    _default_policy = policy


# ── Tool: fs_list_dir ──────────────────────────────────────────────────────────


@tool(
    description=(
        "List the contents of a directory. "
        "Returns a list of entries with name, type (file/dir), and size_bytes. "
        "Use recursive=True to walk subdirectories. "
        "Optionally filter entries by a glob pattern, e.g. '*.py'."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list."},
            "recursive": {
                "type": "boolean",
                "description": "Walk subdirectories recursively. Default false.",
            },
            "pattern": {
                "type": "string",
                "description": "Optional glob filter, e.g. '*.py'. Applied to filenames only.",
            },
        },
        "required": ["path"],
    },
)
def fs_list_dir(
    path: str,
    recursive: bool = False,
    pattern: str | None = None,
) -> list[dict[str, Any]]:
    """List directory contents, optionally recursively and filtered by glob."""
    resolved = _get_policy().resolve_safe(path)

    if not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {resolved}")

    results: list[dict[str, Any]] = []

    def _entry(p: Path) -> dict[str, Any]:
        stat = p.stat()
        return {
            "name": p.name,
            "path": str(p),
            "type": "dir" if p.is_dir() else "file",
            "size_bytes": stat.st_size if p.is_file() else None,
        }

    if recursive:
        for dirpath, dirnames, filenames in os.walk(resolved):
            dirnames.sort()
            dp = Path(dirpath)
            for name in sorted(filenames):
                if pattern is None or fnmatch.fnmatch(name, pattern):
                    try:
                        results.append(_entry(dp / name))
                    except OSError:
                        pass
            for name in sorted(dirnames):
                if pattern is None or fnmatch.fnmatch(name, pattern):
                    try:
                        results.append(_entry(dp / name))
                    except OSError:
                        pass
    else:
        entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
        for entry in entries:
            if pattern is None or fnmatch.fnmatch(entry.name, pattern):
                try:
                    results.append(_entry(entry))
                except OSError:
                    pass

    return results


# ── Tool: fs_read_file ─────────────────────────────────────────────────────────


@tool(
    description=(
        "Read the contents of a text file. "
        "Optionally restrict to a line range with start_line / end_line (1-based, inclusive). "
        "Returns the file content as a string."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
            "start_line": {
                "type": "integer",
                "description": "First line to return (1-based). Omit to read from the start.",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to return (1-based, inclusive). Omit to read to end.",
            },
        },
        "required": ["path"],
    },
)
def fs_read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read a file, optionally sliced to [start_line, end_line]."""
    resolved = _get_policy().resolve_safe(path)

    if not resolved.exists():
        raise FileNotFoundError(f"File does not exist: {resolved}")
    if not resolved.is_file():
        raise IsADirectoryError(f"Path is a directory, not a file: {resolved}")

    text = resolved.read_text(encoding="utf-8", errors="replace")

    if start_line is None and end_line is None:
        return text

    lines = text.splitlines(keepends=True)
    s = (start_line - 1) if start_line else 0
    e = end_line if end_line else len(lines)
    return "".join(lines[s:e])


# ── Tool: fs_write_file ────────────────────────────────────────────────────────


@tool(
    description=(
        "Write content to a file. "
        "mode='create' — fail if file exists; "
        "mode='overwrite' — replace existing content; "
        "mode='append' — add content to the end of the file. "
        "Parent directories are created automatically."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Destination file path."},
            "content": {"type": "string", "description": "Text content to write."},
            "mode": {
                "type": "string",
                "enum": ["create", "overwrite", "append"],
                "description": "Write mode. Default 'overwrite'.",
            },
        },
        "required": ["path", "content"],
    },
)
def fs_write_file(
    path: str,
    content: str,
    mode: str = "overwrite",
) -> str:
    """Write *content* to *path*, returning the resolved path."""
    resolved = _get_policy().resolve_safe(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    if mode == "create" and resolved.exists():
        raise FileExistsError(f"File already exists (use 'overwrite' to replace): {resolved}")

    write_mode = "a" if mode == "append" else "w"
    resolved.write_text(content, encoding="utf-8") if write_mode == "w" else \
        resolved.open("a", encoding="utf-8").write(content)

    return str(resolved)


# ── Tool: fs_search ────────────────────────────────────────────────────────────


@tool(
    description=(
        "Search for files matching a glob pattern. "
        "Searches within 'path' (defaults to home directory). "
        "Returns a list of matching absolute file paths."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match filenames, e.g. '**/*.py'.",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search. Defaults to home directory.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results. Default 50.",
            },
        },
        "required": ["pattern"],
    },
)
def fs_search(
    pattern: str,
    path: str | None = None,
    max_results: int = 50,
) -> list[str]:
    """Return a list of paths matching *pattern* under *path*."""
    root_str = path if path is not None else str(Path.home())
    root = _get_policy().resolve_safe(root_str)

    if not root.exists():
        raise FileNotFoundError(f"Search root does not exist: {root}")

    results: list[str] = []
    for match in root.glob(pattern):
        results.append(str(match))
        if len(results) >= max_results:
            break

    return results
