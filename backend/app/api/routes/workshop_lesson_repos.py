import logging
import uuid
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    GithubAppInstallation,
    GithubInstallationRepository,
    Lesson,
    LessonManifestSync,
    LessonPart,
    LessonRepo,
    User,
)
from app.services.github_app_tokens import (
    GithubAppTokenError,
    mint_installation_access_token,
)
from app.services.github_installation_polling import (
    GithubInstallationPollingError,
    _parse_datetime_maybe,
    fetch_app_installations,
    fetch_installation_repositories,
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
    manifest_count: int
    last_manifest_synced_at: datetime | None = None


class LessonRepoListPublic(BaseModel):
    data: list[LessonRepoListItemPublic]
    count: int


class LessonRepoHealthFilter(str):
    ALL = "all"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class LessonRepoPreviewPartPublic(BaseModel):
    slug: str
    title: str
    ordering: int
    path: str


class LessonRepoPreviewLessonPublic(BaseModel):
    lesson_id: uuid.UUID
    lesson_slug: str
    lesson_title: str
    parts: list[LessonRepoPreviewPartPublic]


class LessonRepoPreviewPublic(BaseModel):
    lesson_repo_id: uuid.UUID
    full_name: str
    default_branch: str
    health: str
    lessons: list[LessonRepoPreviewLessonPublic]


class GithubInstallationListItemPublic(BaseModel):
    installation_id: int
    account_login: str
    account_type: str
    repository_selection: str | None = None
    app_slug: str | None = None
    suspended: bool
    entitled_repositories_count: int
    entitled_repositories: list[str]
    installation_settings_url: str


class GithubInstallationListPublic(BaseModel):
    data: list[GithubInstallationListItemPublic]
    count: int
    install_url: str | None = None


class GithubInstallationRefreshBody(BaseModel):
    include_repositories: bool = False


class GithubInstallationRefreshPublic(BaseModel):
    installations_refreshed: int
    installations_created: int
    installations_updated: int
    repositories_refreshed: int


class GithubInstallationRepositoriesRefreshPublic(BaseModel):
    installation_id: int
    repository_selection: str | None = None
    repositories_total: int
    added: int
    removed: int
    unchanged: int


class GithubInstallationAccessibleRepositoriesPublic(BaseModel):
    installation_id: int
    repository_selection: str | None = None
    full_names: list[str]
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


def _resolve_github_app_install_url(
    installations: list[GithubAppInstallation],
) -> str | None:
    configured_url = settings.GITHUB_APP_INSTALL_URL
    if configured_url:
        return configured_url
    for installation in installations:
        if installation.app_slug:
            return f"https://github.com/apps/{installation.app_slug}/installations/new"
    configured_slug = settings.GITHUB_APP_SLUG
    if configured_slug:
        return f"https://github.com/apps/{configured_slug}/installations/new"
    return None


def _upsert_installation_from_api_row(
    *, session: Session, row: dict[str, Any]
) -> tuple[GithubAppInstallation, bool]:
    install_id_raw = row.get("id")
    if isinstance(install_id_raw, bool) or not isinstance(install_id_raw, int):
        raise GithubInstallationPollingError("Installation row missing valid id")
    account = row.get("account")
    if not isinstance(account, dict):
        raise GithubInstallationPollingError("Installation row missing account")
    account_id_raw = account.get("id")
    account_login_raw = account.get("login")
    account_type_raw = account.get("type")
    if isinstance(account_id_raw, bool) or not isinstance(account_id_raw, int):
        raise GithubInstallationPollingError("Installation account missing valid id")
    if not isinstance(account_login_raw, str) or not account_login_raw.strip():
        raise GithubInstallationPollingError("Installation account missing valid login")
    if not isinstance(account_type_raw, str) or not account_type_raw.strip():
        raise GithubInstallationPollingError("Installation account missing valid type")

    target_type = row.get("target_type")
    repository_selection = row.get("repository_selection")
    app_slug_direct = row.get("app_slug")
    app_payload = row.get("app")
    app_slug = app_slug_direct
    if isinstance(app_payload, dict) and isinstance(app_payload.get("slug"), str):
        app_slug = app_payload.get("slug")

    installation = session.get(GithubAppInstallation, install_id_raw)
    created = installation is None
    if installation is None:
        installation = GithubAppInstallation(
            id=install_id_raw,
            account_id=account_id_raw,
            account_login=account_login_raw.strip(),
            account_type=account_type_raw.strip(),
            target_type=(
                target_type.strip()
                if isinstance(target_type, str) and target_type.strip()
                else account_type_raw.strip()
            ),
            repository_selection=(
                repository_selection.strip()
                if isinstance(repository_selection, str)
                and repository_selection.strip()
                else None
            ),
            app_slug=app_slug.strip()
            if isinstance(app_slug, str) and app_slug
            else None,
            suspended_at=_parse_datetime_maybe(row.get("suspended_at")),
        )
    else:
        installation.account_id = account_id_raw
        installation.account_login = account_login_raw.strip()
        installation.account_type = account_type_raw.strip()
        installation.target_type = (
            target_type.strip()
            if isinstance(target_type, str) and target_type.strip()
            else account_type_raw.strip()
        )
        installation.repository_selection = (
            repository_selection.strip()
            if isinstance(repository_selection, str) and repository_selection.strip()
            else None
        )
        installation.app_slug = (
            app_slug.strip() if isinstance(app_slug, str) and app_slug else None
        )
        installation.suspended_at = _parse_datetime_maybe(row.get("suspended_at"))

    session.add(installation)
    return installation, created


def _sync_github_installation_metadata_from_github_or_fallback(
    *, session: Session
) -> None:
    """Upsert installation rows from GitHub App API (best-effort).

    On polling failure, keep existing database rows so instructors still see stale
    installs when GitHub or app credentials are unavailable.
    """
    try:
        installation_rows = fetch_app_installations(settings=settings)
    except GithubInstallationPollingError as exc:
        logger.warning(
            "GET /workshop/lesson-repos/installations: GitHub metadata sync failed, "
            "using database cache: %s",
            exc,
        )
        return
    except Exception as exc:
        logger.warning(
            "GET /workshop/lesson-repos/installations: unexpected error during "
            "GitHub metadata sync, using database cache: %s",
            exc,
            exc_info=True,
        )
        return
    for row in installation_rows:
        _upsert_installation_from_api_row(session=session, row=row)
    session.commit()


def _reconcile_installation_repositories(
    *, session: Session, installation_id: int, full_names: list[str]
) -> tuple[int, int, int]:
    existing_rows = session.exec(
        select(GithubInstallationRepository).where(
            GithubInstallationRepository.installation_id == installation_id
        )
    ).all()
    existing_map = {row.full_name: row for row in existing_rows}
    target_set = {name.strip() for name in full_names if name.strip()}
    existing_set = set(existing_map.keys())

    to_add = target_set - existing_set
    to_remove = existing_set - target_set
    unchanged = len(existing_set & target_set)

    for repo_name in sorted(to_add):
        session.add(
            GithubInstallationRepository(
                installation_id=installation_id,
                full_name=repo_name,
            )
        )
    for repo_name in sorted(to_remove):
        session.delete(existing_map[repo_name])

    return len(to_add), len(to_remove), unchanged


@router.get("", response_model=LessonRepoListPublic)
def read_lesson_repos(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    installation_id: int | None = Query(default=None, gt=0),
    health: str = Query(default=LessonRepoHealthFilter.ALL),
    q: str | None = Query(default=None, min_length=1, max_length=255),
) -> LessonRepoListPublic:
    """List lesson repos with health + lesson/part counts for instructor tooling."""
    _require_lesson_github_editor(current_user)

    list_stmt = (
        cast(
            Any,
            select(
                LessonRepo,
                func.count(func.distinct(col(Lesson.id))).label("lesson_count"),
                func.count(func.distinct(col(LessonPart.id))).label("part_count"),
                func.count(func.distinct(col(LessonManifestSync.id))).label(
                    "manifest_count"
                ),
            ).add_columns(
                func.max(col(LessonManifestSync.synced_at)).label(
                    "last_manifest_synced_at"
                )
            ),
        )
        .outerjoin(Lesson, col(Lesson.repo_id) == col(LessonRepo.id))
        .outerjoin(LessonPart, col(LessonPart.lesson_id) == col(Lesson.id))
        .outerjoin(
            LessonManifestSync, col(LessonManifestSync.repo_id) == col(LessonRepo.id)
        )
    )
    count_stmt = select(func.count()).select_from(LessonRepo)
    if installation_id is not None:
        list_stmt = list_stmt.where(
            LessonRepo.github_installation_id == installation_id
        )
        count_stmt = count_stmt.where(
            LessonRepo.github_installation_id == installation_id
        )
    if health == LessonRepoHealthFilter.HEALTHY:
        list_stmt = list_stmt.where(LessonRepo.health == "healthy")
        count_stmt = count_stmt.where(LessonRepo.health == "healthy")
    elif health == LessonRepoHealthFilter.UNHEALTHY:
        list_stmt = list_stmt.where(LessonRepo.health != "healthy")
        count_stmt = count_stmt.where(LessonRepo.health != "healthy")
    elif health != LessonRepoHealthFilter.ALL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="health must be one of: all, healthy, unhealthy",
        )
    if q is not None:
        needle = q.strip()
        if needle:
            query_filter = col(LessonRepo.full_name).ilike(f"%{needle}%")
            list_stmt = list_stmt.where(query_filter)
            count_stmt = count_stmt.where(query_filter)
    rows = session.exec(
        list_stmt.group_by(col(LessonRepo.id))
        .order_by(col(LessonRepo.full_name))
        .offset(skip)
        .limit(limit)
    ).all()
    total = session.exec(count_stmt).one()

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
            manifest_count=int(manifest_count or 0),
            last_manifest_synced_at=last_manifest_synced_at,
        )
        for repo, lesson_count, part_count, manifest_count, last_manifest_synced_at in rows
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
    """List GitHub App installations and entitlement summaries.

    Best-effort sync of installation metadata from GitHub before querying the
    database, so empty DB resets still pick up installs without a manual refresh.
    If GitHub is unreachable, responds from the last synced database rows only.
    """
    _require_lesson_github_editor(current_user)

    _sync_github_installation_metadata_from_github_or_fallback(session=session)

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
            installation_settings_url=(
                f"https://github.com/settings/installations/{inst.id}"
            ),
        )
        for inst, entitled_count in rows
    ]
    return GithubInstallationListPublic(
        data=data,
        count=int(total),
        install_url=_resolve_github_app_install_url([inst for inst, _count in rows]),
    )


@router.post(
    "/installations/refresh",
    response_model=GithubInstallationRefreshPublic,
)
def refresh_github_installations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: GithubInstallationRefreshBody,
) -> GithubInstallationRefreshPublic:
    """Poll GitHub App installations and refresh local installation metadata."""
    _require_lesson_github_editor(current_user)
    try:
        installation_rows = fetch_app_installations(settings=settings)
    except GithubInstallationPollingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    created = 0
    refreshed_repositories = 0
    for row in installation_rows:
        installation, was_created = _upsert_installation_from_api_row(
            session=session, row=row
        )
        if was_created:
            created += 1
        if body.include_repositories:
            try:
                repo_names, selection_mode = fetch_installation_repositories(
                    settings=settings,
                    installation_id=installation.id,
                )
            except GithubInstallationPollingError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(exc),
                ) from exc
            if selection_mode:
                installation.repository_selection = selection_mode
                session.add(installation)
            if (selection_mode or installation.repository_selection) == "selected":
                _reconcile_installation_repositories(
                    session=session,
                    installation_id=installation.id,
                    full_names=repo_names,
                )
            else:
                rows = session.exec(
                    select(GithubInstallationRepository).where(
                        GithubInstallationRepository.installation_id == installation.id
                    )
                ).all()
                for existing in rows:
                    session.delete(existing)
            refreshed_repositories += 1

    session.commit()
    refreshed = len(installation_rows)
    return GithubInstallationRefreshPublic(
        installations_refreshed=refreshed,
        installations_created=created,
        installations_updated=max(refreshed - created, 0),
        repositories_refreshed=refreshed_repositories,
    )


@router.post(
    "/installations/{installation_id}/repositories/refresh",
    response_model=GithubInstallationRepositoriesRefreshPublic,
)
def refresh_github_installation_repositories(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    installation_id: int,
) -> GithubInstallationRepositoriesRefreshPublic:
    """Poll one installation's repository grants and reconcile entitlement rows."""
    _require_lesson_github_editor(current_user)
    installation = session.get(GithubAppInstallation, installation_id)
    if installation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown GitHub App installation; refresh installations first",
        )

    try:
        repo_names, selection_mode = fetch_installation_repositories(
            settings=settings,
            installation_id=installation_id,
        )
    except GithubInstallationPollingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if selection_mode:
        installation.repository_selection = selection_mode
    session.add(installation)

    if (selection_mode or installation.repository_selection) == "selected":
        added, removed, unchanged = _reconcile_installation_repositories(
            session=session,
            installation_id=installation_id,
            full_names=repo_names,
        )
    else:
        rows = session.exec(
            select(GithubInstallationRepository).where(
                GithubInstallationRepository.installation_id == installation_id
            )
        ).all()
        removed = len(rows)
        for existing in rows:
            session.delete(existing)
        added = 0
        unchanged = 0

    session.commit()
    return GithubInstallationRepositoriesRefreshPublic(
        installation_id=installation_id,
        repository_selection=installation.repository_selection,
        repositories_total=len(repo_names),
        added=added,
        removed=removed,
        unchanged=unchanged,
    )


@router.get(
    "/installations/{installation_id}/accessible-repositories",
    response_model=GithubInstallationAccessibleRepositoriesPublic,
)
def read_github_installation_accessible_repositories(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    installation_id: int,
) -> GithubInstallationAccessibleRepositoriesPublic:
    """List repositories visible to this installation token (GitHub Installation API).

    Same source as entitlement refresh but read-only—useful for owner/repo autocomplete
    when the installation grants access to all repositories (no persisted entitlement rows).
    """
    _require_lesson_github_editor(current_user)
    installation = session.get(GithubAppInstallation, installation_id)
    if installation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown GitHub App installation; refresh installations first",
        )
    try:
        repo_names, selection_mode = fetch_installation_repositories(
            settings=settings,
            installation_id=installation_id,
        )
    except GithubInstallationPollingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    normalized = sorted(
        {n.strip() for n in repo_names if isinstance(n, str) and n.strip()}
    )
    sel = selection_mode if selection_mode else installation.repository_selection

    return GithubInstallationAccessibleRepositoriesPublic(
        installation_id=installation_id,
        repository_selection=sel,
        full_names=normalized,
        count=len(normalized),
    )


@router.get("/{lesson_repo_id}/preview", response_model=LessonRepoPreviewPublic)
def read_lesson_repo_preview(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    lesson_repo_id: uuid.UUID,
) -> LessonRepoPreviewPublic:
    """Return lesson + part preview rows for one synced lesson repository."""
    _require_lesson_github_editor(current_user)
    lesson_repo = session.get(LessonRepo, lesson_repo_id)
    if lesson_repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson repo not found",
        )

    lesson_rows = session.exec(
        select(Lesson)
        .where(Lesson.repo_id == lesson_repo_id)
        .order_by(col(Lesson.title), col(Lesson.slug)),
    ).all()

    lessons: list[LessonRepoPreviewLessonPublic] = []
    for lesson in lesson_rows:
        part_rows = session.exec(
            select(LessonPart)
            .where(LessonPart.lesson_id == lesson.id)
            .order_by(col(LessonPart.ordering), col(LessonPart.slug)),
        ).all()
        lessons.append(
            LessonRepoPreviewLessonPublic(
                lesson_id=lesson.id,
                lesson_slug=lesson.slug,
                lesson_title=lesson.title,
                parts=[
                    LessonRepoPreviewPartPublic(
                        slug=part.slug,
                        title=part.title,
                        ordering=int(part.ordering),
                        path=part.path,
                    )
                    for part in part_rows
                ],
            )
        )

    return LessonRepoPreviewPublic(
        lesson_repo_id=lesson_repo.id,
        full_name=lesson_repo.full_name,
        default_branch=lesson_repo.default_branch,
        health=lesson_repo.health,
        lessons=lessons,
    )


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
            detail=("Unknown GitHub App installation; refresh installations first"),
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
