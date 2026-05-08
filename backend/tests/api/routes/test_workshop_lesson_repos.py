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
    Lesson,
    LessonManifestSync,
    LessonPart,
    LessonRepo,
    User,
    get_datetime_utc,
)
from app.services.github_app_tokens import (
    GithubAppTokenError,
    InstallationAccessToken,
)
from app.services.github_installation_polling import GithubInstallationPollingError
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


def test_sync_from_github_selected_installation_refreshes_entitlements_on_demand(
    client: TestClient,
) -> None:
    install_id = 907_500_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"selected-refresh/repo-{uuid.uuid4()}"
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
            "app.api.routes.workshop_lesson_repos.fetch_installation_repositories",
            return_value=([full_name], "selected"),
        ),
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
        entitled = session.exec(
            select(GithubInstallationRepository).where(
                GithubInstallationRepository.installation_id == install_id,
                GithubInstallationRepository.full_name == full_name,
            )
        ).first()
        assert entitled is not None


def test_sync_from_github_logs_completion(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    install_id = 908_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"log-check/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="all",
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
        caplog.at_level("INFO"),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/sync-from-github",
            headers=headers,
            json={"full_name": full_name, "installation_id": install_id},
        )

    assert response.status_code == 200
    assert any("lesson_repo_sync completed" in rec.message for rec in caplog.records)


def test_read_lesson_repos_lists_counts_and_health(client: TestClient) -> None:
    install_id = 909_000_000 + (uuid.uuid4().int % 1_000_000)
    full_name = f"repo-list/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
                suspended_at=None,
            ),
        )
        repo = LessonRepo(
            full_name=full_name,
            default_branch="main",
            health="healthy",
            github_installation_id=install_id,
        )
        session.add(repo)
        session.flush()
        lesson = Lesson(
            repo_id=repo.id,
            slug=f"lesson-{uuid.uuid4()}",
            title="Lesson",
            lesson_sync_generation=1,
        )
        session.add(lesson)
        session.flush()
        session.add(
            LessonPart(
                lesson_id=lesson.id,
                ordering=0,
                slug=f"part-{uuid.uuid4()}",
                title="Part 1",
                path="one.md",
                body_md="# one",
            )
        )
        session.add(
            LessonPart(
                lesson_id=lesson.id,
                ordering=1,
                slug=f"part-{uuid.uuid4()}",
                title="Part 2",
                path="two.md",
                body_md="# two",
            )
        )
        session.add(
            LessonManifestSync(
                repo_id=repo.id,
                lesson_slug=lesson.slug,
                manifest_repo_path="lessons/demo/lesson.manifest.yaml",
                manifest_sha256="a" * 64,
            )
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    row = next((r for r in payload["data"] if r["full_name"] == full_name), None)
    assert row is not None
    assert row["health"] == "healthy"
    assert row["lesson_count"] >= 1
    assert row["part_count"] >= 2
    assert row["manifest_count"] >= 1
    assert row["last_manifest_synced_at"] is not None


def test_read_github_installations_lists_entitlements(client: TestClient) -> None:
    install_id = 910_000_000 + (uuid.uuid4().int % 1_000_000)
    acct_login = f"acct-{uuid.uuid4()}"
    repo_full = f"org/repo-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=2,
                account_login=acct_login,
                account_type="Organization",
                target_type="Organization",
                repository_selection="selected",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.add(
            GithubInstallationRepository(
                installation_id=install_id,
                full_name=repo_full,
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        return_value=[
            {
                "id": install_id,
                "account": {
                    "id": 2,
                    "login": acct_login,
                    "type": "Organization",
                },
                "target_type": "Organization",
                "repository_selection": "selected",
                "app_slug": "lesson-bot",
                "app": {"slug": "lesson-bot"},
                "suspended_at": None,
            },
        ],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    row = next(
        (item for item in payload["data"] if item["installation_id"] == install_id),
        None,
    )
    assert row is not None
    assert row["repository_selection"] == "selected"
    assert row["entitled_repositories_count"] >= 1
    assert len(row["entitled_repositories"]) >= 1
    assert repo_full in row["entitled_repositories"]
    assert row["installation_settings_url"].endswith(f"/{install_id}")
    assert (
        payload["install_url"] == "https://github.com/apps/lesson-bot/installations/new"
    )


def test_read_github_installations_populates_db_from_github_on_get(
    client: TestClient,
) -> None:
    install_id = 940_000_000 + (uuid.uuid4().int % 1_000_000)
    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        return_value=[
            {
                "id": install_id,
                "account": {
                    "id": 42,
                    "login": "from-github-org",
                    "type": "Organization",
                },
                "target_type": "Organization",
                "repository_selection": "all",
                "app_slug": "lesson-bot",
                "suspended_at": None,
            }
        ],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    hit = next(
        (item for item in payload["data"] if item["installation_id"] == install_id),
        None,
    )
    assert hit is not None
    assert hit["account_login"] == "from-github-org"

    with Session(engine) as session:
        row = session.get(GithubAppInstallation, install_id)
        assert row is not None
        assert row.account_login == "from-github-org"


def test_read_github_installations_prunes_removed_installations(
    client: TestClient,
) -> None:
    stale_id = 944_000_000 + (uuid.uuid4().int % 1_000_000)
    remaining_id = 945_000_000 + (uuid.uuid4().int % 1_000_000)
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=stale_id,
                account_id=1,
                account_login="uninstalled",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        return_value=[
            {
                "id": remaining_id,
                "account": {
                    "id": 202,
                    "login": "still-here",
                    "type": "Organization",
                },
                "target_type": "Organization",
                "repository_selection": "all",
                "app_slug": "lesson-bot",
                "suspended_at": None,
            },
        ],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    ids_on_wire = {row["installation_id"] for row in payload["data"]}
    assert stale_id not in ids_on_wire
    assert remaining_id in ids_on_wire

    with Session(engine) as session:
        assert session.get(GithubAppInstallation, stale_id) is None


def test_read_github_installations_github_unreachable_still_returns_db_rows(
    client: TestClient,
) -> None:
    install_id = 941_000_000 + (uuid.uuid4().int % 1_000_000)
    login = f"offline-acct-{uuid.uuid4().hex[:8]}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=2,
                account_login=login,
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        side_effect=GithubInstallationPollingError("offline"),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    hit = next(
        (item for item in payload["data"] if item["installation_id"] == install_id),
        None,
    )
    assert hit is not None
    assert hit["account_login"] == login


def test_read_github_installation_accessible_repositories_returns_sorted_unique(
    client: TestClient,
) -> None:
    install_id = 920_000_000 + (uuid.uuid4().int % 1_000_000)
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=2,
                account_login=f"acct-{uuid.uuid4()}",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_installation_repositories",
        return_value=(["b/z", "a/x", "a/x", "  b/z "], "all"),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations/"
            f"{install_id}/accessible-repositories",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["installation_id"] == install_id
    assert payload["repository_selection"] == "all"
    assert payload["full_names"] == ["a/x", "b/z"]
    assert payload["count"] == 2


def test_read_github_installation_accessible_repositories_returns_404_unknown(
    client: TestClient,
) -> None:
    headers = get_superuser_token_headers(client)
    unknown_id = 777_777_777
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos/installations/"
        f"{unknown_id}/accessible-repositories",
        headers=headers,
    )
    assert response.status_code == 404


def test_read_github_installation_accessible_repositories_returns_503_when_github_fails(
    client: TestClient,
) -> None:
    install_id = 930_000_000 + (uuid.uuid4().int % 1_000_000)
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=2,
                account_login=f"acct-{uuid.uuid4()}",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_installation_repositories",
        side_effect=GithubInstallationPollingError("github down"),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations/"
            f"{install_id}/accessible-repositories",
            headers=headers,
        )
    assert response.status_code == 503


def test_read_github_installations_uses_configured_install_url_when_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings,
        "GITHUB_APP_INSTALL_URL",
        "https://github.com/apps/lesson-bot/installations/new",
    )
    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        return_value=[],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["install_url"] == "https://github.com/apps/lesson-bot/installations/new"
    )


def test_read_github_installations_uses_configured_slug_when_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "GITHUB_APP_INSTALL_URL", None)
    monkeypatch.setattr(settings, "GITHUB_APP_SLUG", "lesson-bot")
    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        return_value=[],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["install_url"] == "https://github.com/apps/lesson-bot/installations/new"
    )


def test_refresh_github_installations_upserts_rows(client: TestClient) -> None:
    install_id = 920_000_000 + (uuid.uuid4().int % 1_000_000)
    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        return_value=[
            {
                "id": install_id,
                "account": {
                    "id": 42,
                    "login": "acct-refresh",
                    "type": "Organization",
                },
                "target_type": "Organization",
                "repository_selection": "selected",
                "app_slug": "lesson-bot",
                "suspended_at": None,
            }
        ],
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations/refresh",
            headers=headers,
            json={"include_repositories": False},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["installations_refreshed"] == 1
    assert payload["installations_created"] == 1
    assert payload["repositories_refreshed"] == 0

    with Session(engine) as session:
        row = session.get(GithubAppInstallation, install_id)
        assert row is not None
        assert row.account_login == "acct-refresh"
        assert row.repository_selection == "selected"
        assert row.app_slug == "lesson-bot"


def test_refresh_github_installations_prunes_removed_rows(client: TestClient) -> None:
    stale_id = 946_000_000 + (uuid.uuid4().int % 1_000_000)
    remaining_id = 947_000_000 + (uuid.uuid4().int % 1_000_000)
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=stale_id,
                account_id=1,
                account_login="gone",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.add(
            GithubAppInstallation(
                id=remaining_id,
                account_id=2,
                account_login="present",
                account_type="Organization",
                target_type="Organization",
                repository_selection="selected",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_app_installations",
        return_value=[
            {
                "id": remaining_id,
                "account": {
                    "id": 303,
                    "login": "present",
                    "type": "Organization",
                },
                "target_type": "Organization",
                "repository_selection": "selected",
                "app_slug": "lesson-bot",
                "suspended_at": None,
            },
        ],
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations/refresh",
            headers=headers,
            json={"include_repositories": False},
        )
    assert response.status_code == 200
    assert response.json()["installations_refreshed"] == 1

    with Session(engine) as session:
        assert session.get(GithubAppInstallation, stale_id) is None
        assert session.get(GithubAppInstallation, remaining_id) is not None


def test_refresh_github_installations_can_refresh_selected_entitlements(
    client: TestClient,
) -> None:
    install_id = 921_000_000 + (uuid.uuid4().int % 1_000_000)
    headers = get_superuser_token_headers(client)
    with (
        patch(
            "app.api.routes.workshop_lesson_repos.fetch_app_installations",
            return_value=[
                {
                    "id": install_id,
                    "account": {
                        "id": 99,
                        "login": "acct-entitlement",
                        "type": "User",
                    },
                    "target_type": "User",
                    "repository_selection": "selected",
                    "app_slug": "lesson-bot",
                    "suspended_at": None,
                }
            ],
        ),
        patch(
            "app.api.routes.workshop_lesson_repos.fetch_installation_repositories",
            return_value=(
                [f"org/repo-{uuid.uuid4()}", f"org/repo-{uuid.uuid4()}"],
                "selected",
            ),
        ),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations/refresh",
            headers=headers,
            json={"include_repositories": True},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["installations_refreshed"] == 1
    assert payload["repositories_refreshed"] == 1

    with Session(engine) as session:
        repo_rows = session.exec(
            select(GithubInstallationRepository).where(
                GithubInstallationRepository.installation_id == install_id
            )
        ).all()
        assert len(repo_rows) == 2


def test_refresh_github_installation_repositories_reconciles_rows(
    client: TestClient,
) -> None:
    install_id = 922_000_000 + (uuid.uuid4().int % 1_000_000)
    existing_repo = f"org/existing-{uuid.uuid4()}"
    kept_repo = f"org/kept-{uuid.uuid4()}"
    added_repo = f"org/added-{uuid.uuid4()}"
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=3,
                account_login="acct-reconcile",
                account_type="Organization",
                target_type="Organization",
                repository_selection="selected",
                app_slug="lesson-bot",
                suspended_at=None,
            )
        )
        session.add(
            GithubInstallationRepository(
                installation_id=install_id,
                full_name=existing_repo,
            )
        )
        session.add(
            GithubInstallationRepository(
                installation_id=install_id,
                full_name=kept_repo,
            )
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    with patch(
        "app.api.routes.workshop_lesson_repos.fetch_installation_repositories",
        return_value=([kept_repo, added_repo], "selected"),
    ):
        response = client.post(
            f"{settings.API_V1_STR}/workshop/lesson-repos/installations/{install_id}/repositories/refresh",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["installation_id"] == install_id
    assert payload["added"] == 1
    assert payload["removed"] == 1
    assert payload["unchanged"] == 1

    with Session(engine) as session:
        repo_rows = session.exec(
            select(GithubInstallationRepository).where(
                GithubInstallationRepository.installation_id == install_id
            )
        ).all()
        names = sorted(row.full_name for row in repo_rows)
        assert names == sorted([kept_repo, added_repo])


def test_refresh_github_installation_repositories_rejects_unknown_installation(
    client: TestClient,
) -> None:
    install_id = 923_000_000 + (uuid.uuid4().int % 1_000_000)
    headers = get_superuser_token_headers(client)
    response = client.post(
        f"{settings.API_V1_STR}/workshop/lesson-repos/installations/{install_id}/repositories/refresh",
        headers=headers,
    )
    assert response.status_code == 404
    assert (
        response.json()["detail"]
        == "Unknown GitHub App installation; refresh installations first"
    )


def test_read_lesson_repo_preview_returns_lessons_and_parts(client: TestClient) -> None:
    install_id = 911_000_000 + (uuid.uuid4().int % 1_000_000)
    repo_id: uuid.UUID | None = None
    repo_full_name: str | None = None
    lesson_slug: str | None = None
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=1,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="all",
                app_slug="x",
                suspended_at=None,
            ),
        )
        repo = LessonRepo(
            full_name=f"preview/repo-{uuid.uuid4()}",
            default_branch="main",
            health="healthy",
            github_installation_id=install_id,
        )
        session.add(repo)
        session.flush()
        repo_id = repo.id
        repo_full_name = repo.full_name
        lesson = Lesson(
            repo_id=repo.id,
            slug=f"preview-lesson-{uuid.uuid4()}",
            title="Preview Lesson",
            lesson_sync_generation=1,
        )
        session.add(lesson)
        session.flush()
        lesson_slug = lesson.slug
        session.add(
            LessonPart(
                lesson_id=lesson.id,
                ordering=0,
                slug=f"part-a-{uuid.uuid4()}",
                title="Part A",
                path="a.md",
                body_md="# A",
            )
        )
        session.add(
            LessonPart(
                lesson_id=lesson.id,
                ordering=1,
                slug=f"part-b-{uuid.uuid4()}",
                title="Part B",
                path="b.md",
                body_md="# B",
            )
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos/{repo_id}/preview",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["lesson_repo_id"] == str(repo_id)
    assert payload["full_name"] == repo_full_name
    assert len(payload["lessons"]) == 1
    lesson_payload = payload["lessons"][0]
    assert lesson_payload["lesson_slug"] == lesson_slug
    assert len(lesson_payload["parts"]) == 2
    assert lesson_payload["parts"][0]["ordering"] == 0
    assert lesson_payload["parts"][0]["path"] == "a.md"


def test_read_lesson_repo_preview_returns_404_unknown_repo(client: TestClient) -> None:
    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos/{uuid.uuid4()}/preview",
        headers=headers,
    )
    assert response.status_code == 404


def test_read_lesson_repos_can_filter_by_installation_id(client: TestClient) -> None:
    install_a = 912_000_000 + (uuid.uuid4().int % 1_000_000)
    install_b = 913_000_000 + (uuid.uuid4().int % 1_000_000)
    repo_a = f"filter-a/repo-{uuid.uuid4()}"
    repo_b = f"filter-b/repo-{uuid.uuid4()}"

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_a,
                account_id=11,
                account_login="acct-a",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            )
        )
        session.add(
            GithubAppInstallation(
                id=install_b,
                account_id=12,
                account_login="acct-b",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            )
        )
        session.add(
            LessonRepo(
                full_name=repo_a,
                default_branch="main",
                health="healthy",
                github_installation_id=install_a,
            )
        )
        session.add(
            LessonRepo(
                full_name=repo_b,
                default_branch="main",
                health="healthy",
                github_installation_id=install_b,
            )
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos?installation_id={install_a}",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    names = {row["full_name"] for row in payload["data"]}
    assert repo_a in names
    assert repo_b not in names


def test_read_lesson_repos_can_filter_unhealthy_only(client: TestClient) -> None:
    install_id = 914_000_000 + (uuid.uuid4().int % 1_000_000)
    healthy_repo = f"health-healthy/repo-{uuid.uuid4()}"
    unhealthy_repo = f"health-unhealthy/repo-{uuid.uuid4()}"

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=13,
                account_login="acct-health",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            )
        )
        session.add(
            LessonRepo(
                full_name=healthy_repo,
                default_branch="main",
                health="healthy",
                github_installation_id=install_id,
            )
        )
        session.add(
            LessonRepo(
                full_name=unhealthy_repo,
                default_branch="main",
                health="degraded",
                github_installation_id=install_id,
            )
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos?health=unhealthy",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    names = {row["full_name"] for row in payload["data"]}
    assert unhealthy_repo in names
    assert healthy_repo not in names


def test_read_lesson_repos_can_filter_healthy_only(client: TestClient) -> None:
    install_id = 915_000_000 + (uuid.uuid4().int % 1_000_000)
    healthy_repo = f"health-only-healthy/repo-{uuid.uuid4()}"
    unhealthy_repo = f"health-only-unhealthy/repo-{uuid.uuid4()}"

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=14,
                account_login="acct-health-only",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            )
        )
        session.add(
            LessonRepo(
                full_name=healthy_repo,
                default_branch="main",
                health="healthy",
                github_installation_id=install_id,
            )
        )
        session.add(
            LessonRepo(
                full_name=unhealthy_repo,
                default_branch="main",
                health="degraded",
                github_installation_id=install_id,
            )
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos?health=healthy",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    names = {row["full_name"] for row in payload["data"]}
    assert healthy_repo in names
    assert unhealthy_repo not in names


def test_read_lesson_repos_rejects_invalid_health_filter(client: TestClient) -> None:
    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos?health=broken",
        headers=headers,
    )
    assert response.status_code == 422


def test_read_lesson_repos_can_filter_by_query(client: TestClient) -> None:
    install_id = 916_000_000 + (uuid.uuid4().int % 1_000_000)
    matching_repo = f"query-filter/workshop-{uuid.uuid4()}"
    other_repo = f"query-filter/other-{uuid.uuid4()}"

    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=install_id,
                account_id=15,
                account_login="acct-query",
                account_type="Organization",
                target_type="Organization",
                repository_selection="all",
                app_slug="lesson-bot",
                suspended_at=None,
            )
        )
        session.add(
            LessonRepo(
                full_name=matching_repo,
                default_branch="main",
                health="healthy",
                github_installation_id=install_id,
            )
        )
        session.add(
            LessonRepo(
                full_name=other_repo,
                default_branch="main",
                health="healthy",
                github_installation_id=install_id,
            )
        )
        session.commit()

    headers = get_superuser_token_headers(client)
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lesson-repos?q=workshop",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    names = {row["full_name"] for row in payload["data"]}
    assert matching_repo in names
    assert other_repo not in names
