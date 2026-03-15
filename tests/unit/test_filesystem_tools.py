"""Unit tests for app/tools/builtin/filesystem.py"""
import pytest
from pathlib import Path

from app.tools.builtin.filesystem import (
    PathPolicy,
    fs_list_dir,
    fs_read_file,
    fs_write_file,
    fs_search,
    set_path_policy,
)


# ── PathPolicy ────────────────────────────────────────────────────────────────


def test_path_policy_allows_home_subdirectory(tmp_path: Path) -> None:
    policy = PathPolicy(allowed_roots=[tmp_path])
    resolved = policy.resolve_safe(str(tmp_path / "subdir" / "file.txt"))
    assert resolved == (tmp_path / "subdir" / "file.txt").resolve()


def test_path_policy_rejects_traversal(tmp_path: Path) -> None:
    policy = PathPolicy(allowed_roots=[tmp_path])
    with pytest.raises(PermissionError, match="traversal"):
        policy.resolve_safe(str(tmp_path / ".." / "escape.txt"))


def test_path_policy_rejects_path_outside_roots(tmp_path: Path) -> None:
    import tempfile
    other = Path(tempfile.gettempdir()) / "other_dir"
    policy = PathPolicy(allowed_roots=[tmp_path])
    with pytest.raises(PermissionError, match="outside allowed roots"):
        policy.resolve_safe(str(other / "file.txt"))


def test_path_policy_empty_roots_allows_any(tmp_path: Path) -> None:
    """Empty roots list = permissive mode; only traversal is blocked."""
    policy = PathPolicy(allowed_roots=[])
    # Should NOT raise
    resolved = policy.resolve_safe(str(tmp_path / "file.txt"))
    assert resolved is not None


# ── fs_list_dir ────────────────────────────────────────────────────────────────


def test_fs_list_dir_basic(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    (tmp_path / "sub").mkdir()

    entries = fs_list_dir(str(tmp_path))
    names = {e["name"] for e in entries}
    assert "a.txt" in names
    assert "b.txt" in names
    assert "sub" in names


def test_fs_list_dir_with_pattern(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.txt").write_text("")

    entries = fs_list_dir(str(tmp_path), pattern="*.py")
    names = [e["name"] for e in entries]
    assert "a.py" in names
    assert "b.txt" not in names


def test_fs_list_dir_recursive(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("deep")

    entries = fs_list_dir(str(tmp_path), recursive=True)
    paths = [e["path"] for e in entries]
    assert any("deep.txt" in p for p in paths)


def test_fs_list_dir_not_found(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    with pytest.raises(FileNotFoundError):
        fs_list_dir(str(tmp_path / "nonexistent"))


def test_fs_list_dir_file_raises(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        fs_list_dir(str(f))


# ── fs_read_file ───────────────────────────────────────────────────────────────


def test_fs_read_file_whole(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")

    content = fs_read_file(str(f))
    assert "line1" in content
    assert "line3" in content


def test_fs_read_file_line_range(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    f = tmp_path / "lines.txt"
    f.write_text("a\nb\nc\nd\ne\n")

    content = fs_read_file(str(f), start_line=2, end_line=3)
    assert "b" in content
    assert "c" in content
    assert "a" not in content
    assert "d" not in content


def test_fs_read_file_not_found(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    with pytest.raises(FileNotFoundError):
        fs_read_file(str(tmp_path / "missing.txt"))


def test_fs_read_file_directory_raises(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    with pytest.raises(IsADirectoryError):
        fs_read_file(str(tmp_path))


# ── fs_write_file ──────────────────────────────────────────────────────────────


def test_fs_write_file_create(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    dest = str(tmp_path / "out.txt")
    result = fs_write_file(dest, "hello", mode="create")
    assert Path(result).read_text() == "hello"


def test_fs_write_file_overwrite(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    dest = tmp_path / "out.txt"
    dest.write_text("old")
    fs_write_file(str(dest), "new", mode="overwrite")
    assert dest.read_text() == "new"


def test_fs_write_file_append(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    dest = tmp_path / "out.txt"
    dest.write_text("first")
    fs_write_file(str(dest), " second", mode="append")
    assert dest.read_text() == "first second"


def test_fs_write_file_create_existing_raises(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    dest = tmp_path / "exists.txt"
    dest.write_text("already here")
    with pytest.raises(FileExistsError):
        fs_write_file(str(dest), "new", mode="create")


def test_fs_write_file_creates_parent_dirs(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    dest = str(tmp_path / "a" / "b" / "c.txt")
    fs_write_file(dest, "content")
    assert Path(dest).exists()


# ── fs_search ─────────────────────────────────────────────────────────────────


def test_fs_search_finds_files(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    (tmp_path / "alpha.py").write_text("")
    (tmp_path / "beta.txt").write_text("")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "gamma.py").write_text("")

    results = fs_search("**/*.py", path=str(tmp_path))
    result_names = [Path(r).name for r in results]
    assert "alpha.py" in result_names
    assert "gamma.py" in result_names
    assert "beta.txt" not in result_names


def test_fs_search_max_results(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("")

    results = fs_search("*.txt", path=str(tmp_path), max_results=3)
    assert len(results) <= 3


def test_fs_search_not_found_raises(tmp_path: Path) -> None:
    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    with pytest.raises(FileNotFoundError):
        fs_search("*.py", path=str(tmp_path / "nonexistent"))
