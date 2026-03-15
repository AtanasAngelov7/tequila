"""Sprint 06 — Code execution built-in tool (§16.7).

Provides:
- ``code_exec`` — run code in a subprocess sandbox (destructive safety)

Supported languages
-------------------
- ``python``  — uses the same interpreter that launched the app (``sys.executable``)
- ``shell``   — ``cmd.exe /c`` on Windows, ``/bin/sh -c`` elsewhere
- ``bash``    — ``bash -c`` (falls back to shell if bash not found)

Safety
------
``code_exec`` is classified ``destructive`` — the approval gate in
``ToolExecutor`` will ask the user to confirm before execution unless the
session policy has ``allow_all=True`` (e.g. automated test runs).

Resource limits
---------------
- Wall-clock timeout: *timeout_s* (default 30 s).  Raises ``TimeoutExpired``.
- Output capture: stdout and stderr are captured and returned; no partial
  streaming during execution.
- No memory / CPU resource limits are applied at the OS level (future work).
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from typing import Any

from app.tools.registry import tool

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_S: int = 30
MAX_OUTPUT_CHARS: int = 50_000  # truncate very large outputs

# ── Language → command builder ────────────────────────────────────────────────


def _build_command(language: str, code: str) -> tuple[list[str], bool]:
    """Return ``(command_list, use_shell)`` for the given *language*."""
    lang = language.lower().strip()

    if lang == "python":
        return [sys.executable, "-c", code], False

    if lang in ("shell", "cmd"):
        if sys.platform == "win32":
            return ["cmd.exe", "/c", code], False
        return ["/bin/sh", "-c", code], False

    if lang == "bash":
        return ["bash", "-c", code], False

    if lang in ("javascript", "js", "node"):
        return ["node", "-e", code], False

    # Fallback: treat as shell
    logger.warning("code_exec: unknown language %r, falling back to shell", language)
    if sys.platform == "win32":
        return ["cmd.exe", "/c", code], False
    return ["/bin/sh", "-c", code], False


# ── Tool: code_exec ────────────────────────────────────────────────────────────


@tool(
    description=(
        "Execute code in a local subprocess sandbox. "
        "Supported languages: python, shell, bash, javascript. "
        "Returns stdout, stderr, exit_code, and runtime_ms. "
        "WARNING: This tool executes code on the host machine. "
        "It requires explicit user approval before running."
    ),
    safety="destructive",
    parameters={
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "description": "Programming language: 'python', 'shell', 'bash', 'javascript'.",
            },
            "code": {
                "type": "string",
                "description": "Source code to execute.",
            },
            "timeout_s": {
                "type": "integer",
                "description": f"Execution timeout in seconds. Default {DEFAULT_TIMEOUT_S}.",
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for the subprocess. Defaults to user home.",
            },
        },
        "required": ["language", "code"],
    },
)
def code_exec(
    language: str,
    code: str,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    working_dir: str | None = None,
) -> dict[str, Any]:
    """Execute *code* in a subprocess and return structured results."""
    import pathlib

    cwd = pathlib.Path(working_dir).expanduser().resolve() if working_dir else pathlib.Path.home()
    cmd, use_shell = _build_command(language, code)

    logger.info("code_exec: language=%r timeout=%ds cwd=%s", language, timeout_s, cwd)
    start = time.monotonic()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(cwd),
            shell=use_shell,
        )
        runtime_ms = int((time.monotonic() - start) * 1000)

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        # Truncate very large outputs to avoid bloating context
        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[:MAX_OUTPUT_CHARS] + f"\n[truncated — output exceeded {MAX_OUTPUT_CHARS} chars]"
        if len(stderr) > MAX_OUTPUT_CHARS:
            stderr = stderr[:MAX_OUTPUT_CHARS] + f"\n[truncated]"

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "runtime_ms": runtime_ms,
        }

    except subprocess.TimeoutExpired:
        runtime_ms = int((time.monotonic() - start) * 1000)
        return {
            "stdout": "",
            "stderr": f"Execution timed out after {timeout_s} seconds.",
            "exit_code": -1,
            "runtime_ms": runtime_ms,
        }

    except FileNotFoundError as exc:
        return {
            "stdout": "",
            "stderr": f"Executable not found: {exc}",
            "exit_code": -1,
            "runtime_ms": 0,
        }
