from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings
from app.services.github_app_tokens import (
    GithubAppTokenError,
    create_github_app_jwt,
    mint_installation_access_token,
)

_GITHUB_API_VERSION = "2022-11-28"


class GithubInstallationPollingError(RuntimeError):
    """Raised when polling GitHub App installation metadata fails."""


def _headers_with_bearer(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }


def _parse_datetime_maybe(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def fetch_app_installations(*, settings: Settings) -> list[dict[str, Any]]:
    """Poll GET /app/installations with pagination."""
    try:
        app_token = create_github_app_jwt(settings=settings)
    except GithubAppTokenError as exc:  # pragma: no cover - covered by callers
        raise GithubInstallationPollingError(str(exc)) from exc

    rows: list[dict[str, Any]] = []
    page = 1
    with httpx.Client(timeout=30.0) as client:
        while True:
            response = client.get(
                "https://api.github.com/app/installations",
                params={"per_page": 100, "page": page},
                headers=_headers_with_bearer(app_token),
            )
            if response.status_code != 200:
                raise GithubInstallationPollingError(
                    "GitHub installations refresh failed "
                    f"({response.status_code}): {response.text}"
                )
            payload = response.json()
            if not isinstance(payload, list):
                raise GithubInstallationPollingError(
                    "Unexpected GitHub installations payload"
                )
            normalized_page: list[dict[str, Any]] = [
                item for item in payload if isinstance(item, dict)
            ]
            rows.extend(normalized_page)
            if len(normalized_page) < 100:
                break
            page += 1
    return rows


def fetch_installation_repositories(
    *, settings: Settings, installation_id: int
) -> tuple[list[str], str | None]:
    """
    Poll GET /installation/repositories and return full_name list + selection mode.
    """
    try:
        token = mint_installation_access_token(
            settings=settings, installation_id=installation_id
        ).token
    except GithubAppTokenError as exc:  # pragma: no cover - covered by callers
        raise GithubInstallationPollingError(str(exc)) from exc

    full_names: list[str] = []
    selection_mode: str | None = None
    page = 1
    with httpx.Client(timeout=30.0) as client:
        while True:
            response = client.get(
                "https://api.github.com/installation/repositories",
                params={"per_page": 100, "page": page},
                headers=_headers_with_bearer(token),
            )
            if response.status_code != 200:
                raise GithubInstallationPollingError(
                    "GitHub installation repositories refresh failed "
                    f"({response.status_code}): {response.text}"
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise GithubInstallationPollingError(
                    "Unexpected GitHub installation repositories payload"
                )
            if selection_mode is None:
                mode = payload.get("repository_selection")
                if isinstance(mode, str):
                    selection_mode = mode

            repositories = payload.get("repositories")
            if not isinstance(repositories, list):
                raise GithubInstallationPollingError(
                    "Unexpected repositories array in payload"
                )

            normalized_page_count = 0
            for repo in repositories:
                if not isinstance(repo, dict):
                    continue
                full_name = repo.get("full_name")
                if isinstance(full_name, str) and full_name.strip():
                    full_names.append(full_name.strip())
                    normalized_page_count += 1

            if normalized_page_count < 100:
                break
            page += 1

    unique_full_names = sorted(set(full_names))
    return unique_full_names, selection_mode


__all__ = [
    "GithubInstallationPollingError",
    "_parse_datetime_maybe",
    "fetch_app_installations",
    "fetch_installation_repositories",
]
