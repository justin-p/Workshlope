import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    GithubAppInstallation,
    GithubInstallationRepository,
    Lesson,
    LessonPart,
    LessonRepo,
    User,
)
from app.services.github_app_tokens import (
    GithubAppTokenError,
    mint_installation_access_token,
)
from app.services.lesson_github_fetch import (
    GithubContentsFetchError,
    fetch_lesson_repo_path_map_from_github,
)
from app.services.lesson_repo_sync import (
    LessonRepoSyncError,
    sync_lesson_repo_from_path_map,
)

router = APIRouter(prefix="/workshop/lesson-repos", tags=["workshop-lesson-repos"])
logger = logging.getLogger(__name__)


def _require_lesson_github_editor(current_user: User) -> None:
    if current_user.is_superuser or current_user.is_instructor:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Instructor privileges required",
    )


class LessonRepoGithubSyncBody(BaseModel):
    full_name: str = Field(max_length=255)
    installation_id: int = Field(gt=0)

    @field_validator("full_name")
    @classmethod
    def normalize_owner_repo(cls, value: str) -> str:
        v = value.strip()
        if v.count("/") != 1:
            raise ValueError("full_name must be owner/repo")
        owner, repo = v.split("/", 1)
        if not owner or not repo:
            raise ValueError("full_name must be owner/repo")
        return f"{owner}/{repo}"


class LessonRepoGithubSyncPublic(BaseModel):
    lesson_repo_id: uuid.UUID
    lessons_synced: int
    full_name: str
    health: str
    default_branch: str


class LessonRepoListItemPublic(BaseModel):
    lesson_repo_id: uuid.UUID
    full_name: str
    default_branch: str
    health: str
    github_installation_id: int | None = None
    last_synced_at: datetime | None = None
    lesson_count: int
    part_count: int


class LessonRepoListPublic(BaseModel):
    data: list[LessonRepoListItemPublic]
    count: int


class GithubInstallationListItemPublic(BaseModel):
    installation_id: int
    account_login: str
    account_type: str
    repository_selection: str | None = None
    app_slug: str | None = None
    suspended: bool
    entitled_repositories_count: int
    entitled_repositories: list[str]


class GithubInstallationListPublic(BaseModel):
    data: list[GithubInstallationListItemPublic]
    count: int


def _require_installation_repo_entitlement(
    *,
    session: Session,
    installation: GithubAppInstallation,
    full_name: str,
) -> None:
    if installation.repository_selection != "selected":
        return
    entitled = session.exec(
        select(GithubInstallationRepository).where(
            GithubInstallationRepository.installation_id == installation.id,
            GithubInstallationRepository.full_name == full_name,
        ),
    ).first()
    if entitled is not None:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Installation is not entitled to this repository; "
            "grant repository access in GitHub App settings and retry"
        ),
    )


@router.get("", response_model=LessonRepoListPublic)
def read_lesson_repos(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> LessonRepoListPublic:
    """List lesson repos with health + lesson/part counts for instructor tooling."""
    _require_lesson_github_editor(current_user)

    rows = session.exec(
        select(
            LessonRepo,
            func.count(col(Lesson.id)).label("lesson_count"),
            func.count(col(LessonPart.id)).label("part_count"),
        )
        .outerjoin(Lesson, col(Lesson.repo_id) == col(LessonRepo.id))
        .outerjoin(LessonPart, col(LessonPart.lesson_id) == col(Lesson.id))
        .group_by(col(LessonRepo.id))
        .order_by(col(LessonRepo.full_name))
        .offset(skip)
        .limit(limit),
    ).all()
    total = session.exec(select(func.count()).select_from(LessonRepo)).one()

    data = [
        LessonRepoListItemPublic(
            lesson_repo_id=repo.id,
            full_name=repo.full_name,
            default_branch=repo.default_branch,
            health=repo.health,
            github_installation_id=repo.github_installation_id,
            last_synced_at=repo.last_synced_at,
            lesson_count=int(lesson_count or 0),
            part_count=int(part_count or 0),
        )
        for repo, lesson_count, part_count in rows
    ]
    return LessonRepoListPublic(data=data, count=int(total))


@router.get("/installations", response_model=GithubInstallationListPublic)
def read_github_installations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> GithubInstallationListPublic:
    """List known GitHub App installations and entitlement summaries."""
    _require_lesson_github_editor(current_user)

    rows = session.exec(
        select(
            GithubAppInstallation,
            func.count(col(GithubInstallationRepository.id)).label(
                "entitled_repositories_count"
            ),
        )
        .outerjoin(
            GithubInstallationRepository,
            col(GithubInstallationRepository.installation_id)
            == col(GithubAppInstallation.id),
        )
        .group_by(col(GithubAppInstallation.id))
        .order_by(
            col(GithubAppInstallation.account_login), col(GithubAppInstallation.id)
        )
        .offset(skip)
        .limit(limit),
    ).all()
    total = session.exec(select(func.count()).select_from(GithubAppInstallation)).one()

    installation_ids = [inst.id for inst, _count in rows]
    entitled_rows = (
        session.exec(
            select(GithubInstallationRepository).where(
                col(GithubInstallationRepository.installation_id).in_(installation_ids)
            )
        ).all()
        if installation_ids
        else []
    )
    entitled_by_installation: dict[int, list[str]] = {}
    for row in entitled_rows:
        entitled_by_installation.setdefault(row.installation_id, []).append(
            row.full_name
        )
    for values in entitled_by_installation.values():
        values.sort()

    data = [
        GithubInstallationListItemPublic(
            installation_id=inst.id,
            account_login=inst.account_login,
            account_type=inst.account_type,
            repository_selection=inst.repository_selection,
            app_slug=inst.app_slug,
            suspended=inst.suspended_at is not None,
            entitled_repositories_count=int(entitled_count or 0),
            entitled_repositories=entitled_by_installation.get(inst.id, []),
        )
        for inst, entitled_count in rows
    ]
    return GithubInstallationListPublic(data=data, count=int(total))


@router.post("/sync-from-github", response_model=LessonRepoGithubSyncPublic)
def sync_lesson_repo_from_github(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: LessonRepoGithubSyncBody,
) -> LessonRepoGithubSyncPublic:
    """Pull ``lessons/`` content from GitHub using an installation token and upsert DB rows."""
    _require_lesson_github_editor(current_user)
    logger.info(
        "lesson_repo_sync requested",
        extra={
            "full_name": body.full_name,
            "installation_id": body.installation_id,
            "actor_user_id": str(current_user.id),
        },
    )

    inst = session.get(GithubAppInstallation, body.installation_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Unknown GitHub App installation; complete a GitHub install webhook first"
            ),
        )
    if inst.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Installation is suspended",
        )
    _require_installation_repo_entitlement(
        session=session,
        installation=inst,
        full_name=body.full_name,
    )

    try:
        installation_token = mint_installation_access_token(
            settings=settings,
            installation_id=body.installation_id,
        )
    except GithubAppTokenError as exc:
        logger.warning(
            "lesson_repo_sync token mint failed",
            extra={
                "full_name": body.full_name,
                "installation_id": body.installation_id,
                "actor_user_id": str(current_user.id),
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        path_map, branch_ref = fetch_lesson_repo_path_map_from_github(
            token=installation_token.token,
            full_name=body.full_name,
            default_branch=None,
        )
    except GithubContentsFetchError as exc:
        logger.warning(
            "lesson_repo_sync github fetch failed",
            extra={
                "full_name": body.full_name,
                "installation_id": body.installation_id,
                "actor_user_id": str(current_user.id),
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    lesson_repo = session.exec(
        select(LessonRepo).where(LessonRepo.full_name == body.full_name),
    ).first()
    if lesson_repo is None:
        lesson_repo = LessonRepo(
            full_name=body.full_name,
            default_branch=branch_ref,
            github_installation_id=body.installation_id,
            health="healthy",
        )
        session.add(lesson_repo)
        session.commit()
        session.refresh(lesson_repo)
    else:
        lesson_repo.default_branch = branch_ref
        lesson_repo.github_installation_id = body.installation_id
        session.add(lesson_repo)
        session.commit()
        session.refresh(lesson_repo)

    try:
        synced = sync_lesson_repo_from_path_map(
            session=session,
            lesson_repo=lesson_repo,
            path_to_content=path_map,
        )
    except LessonRepoSyncError as exc:
        logger.warning(
            "lesson_repo_sync apply failed",
            extra={
                "full_name": body.full_name,
                "installation_id": body.installation_id,
                "actor_user_id": str(current_user.id),
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    session.refresh(lesson_repo)
    logger.info(
        "lesson_repo_sync completed",
        extra={
            "full_name": lesson_repo.full_name,
            "installation_id": body.installation_id,
            "actor_user_id": str(current_user.id),
            "lessons_synced": synced,
            "health": lesson_repo.health,
            "default_branch": lesson_repo.default_branch,
        },
    )
    return LessonRepoGithubSyncPublic(
        lesson_repo_id=lesson_repo.id,
        lessons_synced=synced,
        full_name=lesson_repo.full_name,
        health=lesson_repo.health,
        default_branch=lesson_repo.default_branch,
    )
