# -*- mode: python ; coding: utf-8 -*-
# tequila.spec — PyInstaller --onedir bundle specification (Sprint 15 §29.1)
#
# Usage:
#   pyinstaller build/tequila.spec
#
# Output: dist/tequila/   (--onedir bundle, then wrapped by Inno Setup installer)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # repo root (parent of build/)

# ── Hidden imports ────────────────────────────────────────────────────────────
# Packages that PyInstaller cannot auto-detect via static analysis.

hidden_imports = [
    # uvicorn ASGI server
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # FastAPI / Starlette internals
    "starlette.routing",
    "starlette.staticfiles",
    "starlette.responses",
    # aiosqlite
    "aiosqlite",
    # Alembic
    "alembic",
    "alembic.runtime.migration",
    "alembic.operations",
    # pydantic / pydantic-settings
    "pydantic",
    "pydantic_settings",
    # cryptography
    "cryptography",
    "cryptography.hazmat.primitives.kdf.pbkdf2",
    # anthropic / openai clients
    "anthropic",
    "openai",
    "tiktoken",
    # numpy (used by embedding search)
    "numpy",
    # httpx
    "httpx",
    # multipart
    "multipart",
    # jinja2
    "jinja2",
    # Application submodules that are loaded dynamically
    "app.api.routers",
    "app.agent",
    "app.auth",
    "app.budget",
    "app.audit",
    "app.backup",
    "app.files",
    "app.knowledge",
    "app.memory",
    "app.notifications",
    "app.plugins",
    "app.providers",
    "app.scheduler",
    "app.sessions",
    "app.tools",
    "app.workflows",
]

hidden_imports += collect_submodules("uvicorn")
hidden_imports += collect_submodules("anthropic")
hidden_imports += collect_submodules("openai")
hidden_imports += collect_submodules("tiktoken")

# ── Data files ────────────────────────────────────────────────────────────────
# Tuples of (source_glob_or_dir, destination_dir_in_bundle)

datas = []

# Frontend build output (produced by `npm run build`)
frontend_dist = ROOT / "frontend" / "dist"
datas.append((str(frontend_dist), "frontend/dist"))

# Alembic migrations
datas.append((str(ROOT / "alembic"), "alembic"))
datas.append((str(ROOT / "alembic.ini"), "."))

# Default config template (if .env.example exists)
env_example = ROOT / ".env.example"
if env_example.exists():
    datas.append((str(env_example), "."))

# tiktoken encoding data
datas += collect_data_files("tiktoken")

# OpenAI, Anthropic certificate bundles / data
datas += collect_data_files("anthropic")
datas += collect_data_files("certifi")

# ── Analysis ──────────────────────────────────────────────────────────────────

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional ML deps if not needed
        "matplotlib",
        "PIL",
        "scipy",
        "sklearn",
        "torch",
        "tensorflow",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tequila",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "frontend" / "public" / "favicon.ico") if (ROOT / "frontend" / "public" / "favicon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="tequila",         # output: dist/tequila/
)
