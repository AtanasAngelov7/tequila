"""GitHub releases API version checker (Sprint 16 §29.5)."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.update.models import VersionInfo

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "tequila-updater/1",
}


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse ``"v1.2.3"`` or ``"1.2.3"`` → ``(1, 2, 3)``."""
    v = v.lstrip("vV").strip()
    parts = re.split(r"[.\-]", v)
    result = []
    for p in parts[:3]:
        try:
            result.append(int(p))
        except ValueError:
            break
    while len(result) < 3:
        result.append(0)
    return tuple(result)


def _is_newer(candidate: str | tuple, current: str | tuple) -> bool:
    """Return ``True`` if *candidate* is strictly newer than *current*."""
    a = candidate if isinstance(candidate, tuple) else _parse_version(candidate)
    b = current if isinstance(current, tuple) else _parse_version(current)
    return a > b


async def check_github_releases(
    repo: str,
    *,
    include_prerelease: bool = False,
) -> "VersionInfo | None":
    """Query GitHub releases for *repo* and return the latest ``VersionInfo``.

    Returns ``None`` when:
    - The repo has no releases.
    - The HTTP request fails (logged at WARNING).
    """
    from app.update.models import VersionInfo

    url = f"{_GITHUB_API}/repos/{repo}/releases"
    params = {"per_page": 10}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_HEADERS, params=params)
        if resp.status_code == 404:
            logger.warning("Update check: repo %r not found (404).", repo)
            return None
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Update check failed: %s", exc)
        return None

    releases = resp.json()
    if not isinstance(releases, list):
        return None

    # Pick the first release that matches the channel preference.
    for release in releases:
        if not include_prerelease and release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        body = release.get("body", "")
        published = release.get("published_at", "")

        # Find Windows installer asset (*.exe).
        installer_url = ""
        sha256 = None
        for asset in release.get("assets", []):
            name: str = asset.get("name", "")
            if name.endswith(".exe"):
                installer_url = asset.get("browser_download_url", "")
            if name.endswith(".sha256"):
                # Optionally download and read, skip for now
                pass

        if not installer_url:
            # No installer asset — skip this release.
            continue

        return VersionInfo(
            version=tag.lstrip("v"),
            release_date=published[:10] if published else "",
            changelog=body,
            download_url=installer_url,
            checksum_sha256=sha256,
            is_prerelease=bool(release.get("prerelease")),
        )

    return None


def is_newer_than_current(candidate_version: str, current_version: str) -> bool:
    """Expose version comparison for tests and service layer."""
    return _is_newer(candidate_version, current_version)
