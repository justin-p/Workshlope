"""Instructor GitHub → DB lesson sync (mocked GitHub surface)."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import GithubAppInstallation
from app.services.github_app_tokens import InstallationAccessToken
from tests.utils.utils import get_superuser_token_headers


def _tree() -> dict[str, str]:
    return {
        "lessons/demo/lesson.manifest.yaml": """
version: 1
lesson:
  slug: demo-lesson
  title: Demo Lesson
parts:
  - slug: one
    title: Part One
    path: one.md
""",
        "lessons/demo/one.md": "# One",
    }


def test_sync_from_github_returns_404_unknown_installation(client: TestClient) -> None:
    headers = get_superuser_token_headers(client)
    response = client.post(
        f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
        headers=headers,
        json={"full_name": "acme/unknown-repo", "installation_id": 777_777_777},
    )
    assert response.status_code == 404


def test_sync_from_github_denies_trainee(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
        headers=normal_user_token_headers,
        json={"full_name": "acme/demo-repo", "installation_id": 1},
    )
    assert response.status_code == 403


def test_sync_from_github_happy_path_mocked_github(client: TestClient) -> None:
    install_id = 800_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"sync-test/repo-{uuid.uuid4()}"
    headers = get_superuser_token_headers(client)

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=321,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    mocked_token = InstallationAccessToken(token="mock-github-token", expires_at=None)

    with (
        patch(
            "app.api.routes.workshop_lesson_repos.mint_installation_access_token",
            return_value=mocked_token,
        ),
        patch(
            "app.api.routes.workshop_lesson_repos.fetch_lesson_repo_path_map_from_github",
            return_value=(_tree(), "main"),
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
            headers=headers,
            json={"full_name": full_name, "installation_id": install_id},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["lessons_synced"] == 1
    assert data["health"] == "healthy"
    assert data["full_name"] == full_name

    with Session(engine) as session:
        installation = session.get(GithubAppInstallation, install_id)
        if installation is not None:
            session.delete(installation)
            session.commit()
