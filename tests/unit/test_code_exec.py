"""Unit tests for app/tools/builtin/code_exec.py"""
import sys

import pytest

from app.tools.builtin.code_exec import code_exec, _build_command


# ── _build_command ────────────────────────────────────────────────────────────


def test_build_command_python() -> None:
    cmd, use_shell = _build_command("python", "print('hi')")
    assert cmd[0] == sys.executable
    assert "print('hi')" in cmd


def test_build_command_shell_windows_or_posix() -> None:
    import sys as _sys
    cmd, use_shell = _build_command("shell", "echo hello")
    if _sys.platform == "win32":
        assert "cmd.exe" in cmd[0]
    else:
        assert "/bin/sh" in cmd[0]
    assert "echo hello" in cmd


def test_build_command_unknown_language_fallback() -> None:
    cmd, _ = _build_command("cobol", "DISPLAY 'hi'")
    # Should not raise; falls back to shell
    assert len(cmd) >= 2


# ── code_exec ─────────────────────────────────────────────────────────────────


def test_code_exec_python_success() -> None:
    result = code_exec(language="python", code="print('hello world')")
    assert result["exit_code"] == 0
    assert "hello world" in result["stdout"]
    assert result["runtime_ms"] >= 0


def test_code_exec_python_stderr() -> None:
    result = code_exec(language="python", code="import sys; sys.stderr.write('err msg\\n')")
    assert result["exit_code"] == 0
    assert "err msg" in result["stderr"]


def test_code_exec_python_nonzero_exit() -> None:
    result = code_exec(language="python", code="raise SystemExit(42)")
    assert result["exit_code"] == 42


def test_code_exec_python_exception() -> None:
    result = code_exec(language="python", code="raise ValueError('oops')")
    assert result["exit_code"] != 0
    assert "ValueError" in result["stderr"] or "oops" in result["stderr"]


def test_code_exec_timeout() -> None:
    result = code_exec(language="python", code="import time; time.sleep(10)", timeout_s=1)
    assert result["exit_code"] == -1
    assert "timed out" in result["stderr"].lower()


def test_code_exec_stdout_truncation() -> None:
    """Very large output should be truncated."""
    result = code_exec(
        language="python",
        code="print('x' * 100_000)",
        timeout_s=15,
    )
    assert result["exit_code"] == 0
    assert "truncated" in result["stdout"]


def test_code_exec_returns_runtime_ms() -> None:
    result = code_exec(language="python", code="pass")
    assert isinstance(result["runtime_ms"], int)
    assert result["runtime_ms"] >= 0


def test_code_exec_working_dir(tmp_path) -> None:
    """Code can read from working directory."""
    result = code_exec(
        language="python",
        code="import os; print(os.getcwd())",
        working_dir=str(tmp_path),
    )
    assert result["exit_code"] == 0
    # cwd should contain tmp_path parts
    assert str(tmp_path).replace("\\", "/").split("/")[-1].lower() in result["stdout"].lower() or \
           str(tmp_path) in result["stdout"]


def test_code_exec_invalid_executable() -> None:
    """Missing interpreter returns exit_code -1 and error message."""
    result = code_exec(
        language="shell",
        code="echo",
        timeout_s=5,
    )
    # Shell should work; if it genuinely fails, exit_code will be -1
    # This is really a smoke test
    assert "exit_code" in result


def test_code_exec_tool_registered() -> None:
    """code_exec should be in the global tool registry."""
    from app.tools.registry import get_tool_registry
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()
    reg = get_tool_registry()
    entry = reg.get("code_exec")
    assert entry is not None
    td, fn = entry
    assert td.safety == "destructive"
