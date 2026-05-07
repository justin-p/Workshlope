"""Instructor GitHub → DB lesson sync (mocked GitHub surface)."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    GithubAppInstallation,
    GithubInstallationRepository,
    LessonRepo,
    User,
    get_datetime_utc,
)
from app.services.github_app_tokens import (
    GithubAppTokenError,
    InstallationAccessToken,
)
from app.services.lesson_github_fetch import GithubContentsFetchError
from app.services.lesson_repo_sync import LessonRepoSyncError
from tests.utils.user import authentication_token_from_email
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


def test_sync_from_github_returns_422_invalid_full_name(client: TestClient) -> None:
    headers = get_superuser_token_headers(client)
    response = client.post(
        f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
        headers=headers,
        json={"full_name": "not-a-slash-pair", "installation_id": 1},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "full_name",
    [" /only-right", "only-left/ ", " / "],
)
def test_sync_from_github_returns_422_malformed_owner_repo(
    client: TestClient, full_name: str
) -> None:
    headers = get_superuser_token_headers(client)
    response = client.post(
        f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
        headers=headers,
        json={"full_name": full_name, "installation_id": 1},
    )
    assert response.status_code == 422


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


def test_sync_from_github_returns_409_when_installation_suspended(
    client: TestClient,
) -> None:
    install_id = 900_000_000 + (uuid.uuid4().int % 1_000_000)

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="t",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
                suspended_at=get_datetime_utc(),
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    response = client.post(
        f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
        headers=headers,
        json={"full_name": "a/b", "installation_id": install_id},
    )
    assert response.status_code == 409

    with Session(engine) as session:
        row = session.get(GithubAppInstallation, install_id)
        if row is not None:
            session.delete(row)
            session.commit()


def test_sync_from_github_returns_503_when_token_mint_fails(
    client: TestClient,
) -> None:
    install_id = 901_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"mint-fail/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="t",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
                suspended_at=None,
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.mint_installation_access_token",
        side_effect=GithubAppTokenError("no key"),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
            headers=headers,
            json={"full_name": full_name, "installation_id": install_id},
        )
    assert response.status_code == 503

    with Session(engine) as session:
        row = session.get(GithubAppInstallation, install_id)
        if row is not None:
            session.delete(row)
            session.commit()


def test_sync_from_github_returns_400_when_github_fetch_fails(
    client: TestClient,
) -> None:
    install_id = 902_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"fetch-fail/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="t",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
                suspended_at=None,
            ),
        )
        session.commit()

    mocked_token = InstallationAccessToken(token="t", expires_at=None)
    headers = get_superuser_token_headers(client)
    with (
        patch(
            "app.api.routes.workshop_lesson_repos.mint_installation_access_token",
            return_value=mocked_token,
        ),
        patch(
            "app.api.routes.workshop_lesson_repos.fetch_lesson_repo_path_map_from_github",
            side_effect=GithubContentsFetchError("lessons missing"),
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
            headers=headers,
            json={"full_name": full_name, "installation_id": install_id},
        )
    assert response.status_code == 400

    with Session(engine) as session:
        row = session.get(GithubAppInstallation, install_id)
        if row is not None:
            session.delete(row)
            session.commit()


def test_sync_from_github_updates_existing_lesson_repo_row(client: TestClient) -> None:
    install_id = 903_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"sync-update/repo-{uuid.uuid4()}"

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="t",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
                suspended_at=None,
            ),
        )
        session.add(
            LessonRepo(
                full_name=full_name,
                default_branch="old-branch",
                github_installation_id=install_id,
                health="healthy",
            ),
        )
        session.commit()

    mocked_token = InstallationAccessToken(token="mock-github-token", expires_at=None)
    headers = get_superuser_token_headers(client)
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

    with Session(engine) as session:
        row = session.exec(
            select(LessonRepo).where(LessonRepo.full_name == full_name),
        ).first()
        assert row is not None
        assert row.default_branch == "main"
        assert row.github_installation_id == install_id
        session.delete(row)
        session.commit()

    with Session(engine) as session:
        inst = session.get(GithubAppInstallation, install_id)
        if inst is not None:
            session.delete(inst)
            session.commit()


def test_sync_from_github_returns_422_when_sync_raises(
    client: TestClient,
) -> None:
    install_id = 905_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"sync-bad/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="t",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
                suspended_at=None,
            ),
        )
        session.commit()

    mocked_token = InstallationAccessToken(token="t", expires_at=None)
    headers = get_superuser_token_headers(client)
    with (
        patch(
            "app.api.routes.workshop_lesson_repos.mint_installation_access_token",
            return_value=mocked_token,
        ),
        patch(
            "app.api.routes.workshop_lesson_repos.fetch_lesson_repo_path_map_from_github",
            return_value=({"lessons/z/lesson.manifest.yaml": "bad"}, "main"),
        ),
        patch(
            "app.api.routes.workshop_lesson_repos.sync_lesson_repo_from_path_map",
            side_effect=LessonRepoSyncError("manifest invalid"),
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
            headers=headers,
            json={"full_name": full_name, "installation_id": install_id},
        )
    assert response.status_code == 422

    with Session(engine) as session:
        repo = session.exec(
            select(LessonRepo).where(LessonRepo.full_name == full_name),
        ).first()
        if repo is not None:
            session.delete(repo)
        inst = session.get(GithubAppInstallation, install_id)
        if inst is not None:
            session.delete(inst)
        session.commit()


def test_sync_from_github_allows_instructor_not_only_superuser(
    client: TestClient, db: Session
) -> None:
    email = f"lesson-sync-inst-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=email, db=db)
    user = db.exec(select(User).where(User.email == email)).first()
    assert user is not None
    user.is_instructor = True
    db.add(user)
    db.commit()
    db.refresh(user)

    install_id = 904_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"inst-sync/repo-{uuid.uuid4()}"
    token_headers = authentication_token_from_email(client=client, email=email, db=db)

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="t",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
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
            headers=token_headers,
            json={"full_name": full_name, "installation_id": install_id},
        )
    assert response.status_code == 200

    with Session(engine) as session:
        inst = session.get(GithubAppInstallation, install_id)
        if inst is not None:
            session.delete(inst)
            session.commit()
        repo = session.exec(
            select(LessonRepo).where(LessonRepo.full_name == full_name),
        ).first()
        if repo is not None:
            session.delete(repo)
            session.commit()


def test_sync_from_github_selected_installation_requires_repo_entitlement(
    client: TestClient,
) -> None:
    install_id = 906_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"selected-block/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="selected",
                app_slug="x",
                suspended_at=None,
            ),
        )
        session.commit()

    mocked_token = InstallationAccessToken(token="mock-github-token", expires_at=None)
    headers = get_superuser_token_headers(client)
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
    assert response.status_code == 403

    with Session(engine) as session:
        inst = session.get(GithubAppInstallation, install_id)
        if inst is not None:
            session.delete(inst)
            session.commit()


def test_sync_from_github_selected_installation_allows_entitled_repo(
    client: TestClient,
) -> None:
    install_id = 907_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"selected-allow/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="selected",
                app_slug="x",
                suspended_at=None,
            ),
        )
        session.add(
            GithubInstallationRepository(
                installation_id=install_id,
                full_name=full_name,
            ),
        )
        session.commit()

    mocked_token = InstallationAccessToken(token="mock-github-token", expires_at=None)
    headers = get_superuser_token_headers(client)
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
