"""Unit tests for the auto-update module (Sprint 16 §29.5 D6).

Tests cover:
  - Version string parsing and comparison
  - UpdateState model serialisation
  - UpdateService.check() (mock httpx)
  - UpdateService.download() (mock httpx streaming)
  - UpdateService.apply() validation guards
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.update.checker import _is_newer, _parse_version, is_newer_than_current
from app.update.models import UpdateConfig, UpdateState, VersionInfo
from app.update.service import UpdateService


# ── Version parsing ───────────────────────────────────────────────────────────

class TestParseVersion:
    def test_plain(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_v_prefix(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_v_prefix_capital(self):
        assert _parse_version("V2.0.0") == (2, 0, 0)

    def test_zeros(self):
        assert _parse_version("0.0.1") == (0, 0, 1)

    def test_two_parts(self):
        assert _parse_version("2.0") == (2, 0, 0)

    def test_dash_suffix(self):
        # Only the first three numeric parts matter
        result = _parse_version("1.2.3-beta.1")
        assert result[0] == 1
        assert result[1] == 2
        assert result[2] == 3


class TestIsNewer:
    def test_newer_patch(self):
        assert _is_newer((1, 2, 4), (1, 2, 3)) is True

    def test_newer_minor(self):
        assert _is_newer((1, 3, 0), (1, 2, 9)) is True

    def test_newer_major(self):
        assert _is_newer((2, 0, 0), (1, 9, 9)) is True

    def test_same(self):
        assert _is_newer((1, 2, 3), (1, 2, 3)) is False

    def test_older(self):
        assert _is_newer((1, 1, 0), (1, 2, 0)) is False


class TestIsNewerThanCurrent:
    def test_newer(self):
        assert is_newer_than_current("0.2.0", "0.1.0") is True

    def test_same(self):
        assert is_newer_than_current("0.1.0", "0.1.0") is False

    def test_older(self):
        assert is_newer_than_current("0.0.9", "0.1.0") is False

    def test_major_bump(self):
        assert is_newer_than_current("1.0.0", "0.9.9") is True


# ── Model tests ───────────────────────────────────────────────────────────────

class TestUpdateStateModel:
    def test_defaults(self):
        state = UpdateState()
        assert state.status == "idle"
        assert state.download_progress == 0.0
        assert state.latest_version is None

    def test_round_trip(self):
        state = UpdateState(current_version="0.1.0", status="available", latest_version="0.2.0")
        data = json.loads(state.model_dump_json())
        restored = UpdateState(**data)
        assert restored.latest_version == "0.2.0"
        assert restored.status == "available"


class TestUpdateConfigModel:
    def test_defaults(self):
        cfg = UpdateConfig()
        assert cfg.enabled is True
        assert cfg.update_channel == "stable"
        assert cfg.check_interval_hours == 24


# ── UpdateService tests ───────────────────────────────────────────────────────

_MOCK_VERSION_INFO = VersionInfo(
    version="0.2.0",
    release_date="2026-01-01T00:00:00Z",
    changelog="Bug fixes and new features.",
    download_url="https://example.com/TequilaSetup-0.2.0.exe",
    checksum_sha256=None,
    is_prerelease=False,
)


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "update_state.json"


@pytest.fixture
def config() -> UpdateConfig:
    return UpdateConfig(
        enabled=True,
        check_interval_hours=24,
        github_repo="tequila-ai/tequila",
        auto_download=False,
    )


@pytest.fixture
def svc(config: UpdateConfig, state_path: Path) -> UpdateService:
    with patch("app.update.service._current_version", return_value="0.1.0"):
        yield UpdateService(config, state_path)


class TestUpdateServiceCheck:
    @pytest.mark.asyncio
    async def test_check_new_version_available(self, svc: UpdateService):
        with patch(
            "app.update.service.check_github_releases",
            new=AsyncMock(return_value=_MOCK_VERSION_INFO),
        ):
            state = await svc.check()

        assert state.status == "available"
        assert state.latest_version == "0.2.0"
        assert state.error is None

    @pytest.mark.asyncio
    async def test_check_up_to_date(self, svc: UpdateService):
        current_info = VersionInfo(
            version="0.1.0",
            release_date="2025-01-01T00:00:00Z",
            changelog="",
            download_url="https://example.com/TequilaSetup-0.1.0.exe",
        )
        with patch(
            "app.update.service.check_github_releases",
            new=AsyncMock(return_value=current_info),
        ):
            state = await svc.check()

        assert state.status == "idle"
        assert state.error is None

    @pytest.mark.asyncio
    async def test_check_network_error(self, svc: UpdateService):
        with patch(
            "app.update.service.check_github_releases",
            new=AsyncMock(side_effect=Exception("network timeout")),
        ):
            state = await svc.check()

        assert state.status == "error"
        assert "network timeout" in (state.error or "")

    @pytest.mark.asyncio
    async def test_check_disabled(self, state_path: Path):
        cfg = UpdateConfig(enabled=False)
        with patch("app.update.service._current_version", return_value="0.1.0"):
            svc = UpdateService(cfg, state_path)
        with patch(
            "app.update.service.check_github_releases",
            new=AsyncMock(return_value=_MOCK_VERSION_INFO),
        ) as mock_check:
            state = await svc.check()

        mock_check.assert_not_called()
        assert state.status == "idle"

    @pytest.mark.asyncio
    async def test_check_persists_state(self, svc: UpdateService, state_path: Path):
        with patch(
            "app.update.service.check_github_releases",
            new=AsyncMock(return_value=_MOCK_VERSION_INFO),
        ):
            await svc.check()

        assert state_path.exists()
        saved = json.loads(state_path.read_text())
        assert saved["latest_version"] == "0.2.0"


class TestUpdateServiceDownload:
    @pytest.mark.asyncio
    async def test_download_no_update_available(self, svc: UpdateService):
        """download() when no update is available should set error state."""
        with patch(
            "app.update.service.check_github_releases",
            new=AsyncMock(return_value=None),
        ):
            state = await svc.download()

        assert state.status == "error"
        assert state.error is not None

    @pytest.mark.asyncio
    async def test_download_success(self, svc: UpdateService, tmp_path: Path):
        from unittest.mock import call

        written_chunks: list[bytes] = []

        def fake_download_sync(url, dest, info):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"fake installer")

        with (
            patch(
                "app.update.service.check_github_releases",
                new=AsyncMock(return_value=_MOCK_VERSION_INFO),
            ),
            patch("app.paths.data_dir", return_value=tmp_path),
            patch.object(svc, "_download_sync", side_effect=fake_download_sync),
        ):
            state = await svc.download()

        assert state.status == "ready"
        assert state.download_progress == 1.0
        assert state.download_path is not None


class TestUpdateServiceApply:
    @pytest.mark.asyncio
    async def test_apply_no_installer(self, svc: UpdateService):
        with pytest.raises(RuntimeError, match="No installer ready"):
            await svc.apply()

    @pytest.mark.asyncio
    async def test_apply_missing_file(self, svc: UpdateService, tmp_path: Path):
        svc._state.status = "ready"
        svc._state.download_path = str(tmp_path / "missing.exe")
        with pytest.raises(FileNotFoundError):
            await svc.apply()

    @pytest.mark.asyncio
    async def test_apply_launches_installer_and_exits(
        self, svc: UpdateService, tmp_path: Path
    ):
        installer = tmp_path / "TequilaSetup-0.2.0.exe"
        installer.write_bytes(b"fake installer")
        svc._state.status = "ready"
        svc._state.download_path = str(installer)

        with (
            patch("platform.system", return_value="Windows"),
            patch("subprocess.Popen") as mock_popen,
            patch("sys.exit") as mock_exit,
        ):
            await svc.apply()

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "/SILENT" in args
        mock_exit.assert_called_once_with(0)


class TestUpdateServiceGetState:
    def test_get_state_returns_current(self, svc: UpdateService):
        state = svc.get_state()
        assert state.current_version == "0.1.0"
        assert state.status == "idle"
