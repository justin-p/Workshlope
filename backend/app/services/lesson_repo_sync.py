from __future__ import annotations

import posixpath
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath

from sqlmodel import Session, col, func, select

from app.models import (
    Lesson,
    LessonManifestSync,
    LessonPart,
    LessonRepo,
    WorkshopBadgeDefinition,
    WorkshopBadgeGrant,
    get_datetime_utc,
)
from app.services.lesson_manifest import ManifestValidationError, parse_lesson_manifest


class LessonRepoSyncError(RuntimeError):
    """Hard sync failure: invalid manifest, unsafe paths, duplicate slugs, or missing files."""


@dataclass(frozen=True)
class _PreparedLessonSync:
    manifest_repo_path: str
    manifest_sha256: str
    lesson_slug: str
    title: str
    summary: str | None
    parts: list[tuple[int, str, str, str, int | None, str]]
    # ordering, slug, title, path, estimated_minutes, body_md
    badges: list[tuple[str, str, int, str | None]]
    # manifest_badge_slug, title, points, description


def _reject_unsafe_repo_path(path: str) -> None:
    if not path or path.startswith("/"):
        raise LessonRepoSyncError(f"Unsafe repo path (absolute or empty): {path!r}")
    norm = posixpath.normpath(path)
    if norm.startswith("../") or "/../" in f"/{norm}/":
        raise LessonRepoSyncError(f"Unsafe repo path (traversal): {path!r}")


def _part_file_key(*, manifest_repo_path: str, part_relative_path: str) -> str:
    parent = PurePosixPath(manifest_repo_path).parent.as_posix()
    if parent == ".":
        joined = part_relative_path
    else:
        joined = posixpath.normpath(f"{parent}/{part_relative_path}")
    _reject_unsafe_repo_path(joined)
    return joined


def _manifest_paths(paths: Iterable[str]) -> list[str]:
    manifests = sorted(p for p in paths if p.endswith("lesson.manifest.yaml"))
    for m in manifests:
        _reject_unsafe_repo_path(m)
    return manifests


def prepare_lesson_sync_ops_from_path_map(
    path_to_content: dict[str, str],
) -> list[_PreparedLessonSync]:
    """
    Validate each discovered manifest and every referenced markdown body (phase 1;
    no database writes).

    Keys use forward slashes relative to the repository root. Lesson manifests
    are files whose paths end with ``lesson.manifest.yaml``.
    """
    if not path_to_content:
        raise LessonRepoSyncError("Empty path map")

    manifest_repo_paths = _manifest_paths(path_to_content.keys())
    if not manifest_repo_paths:
        raise LessonRepoSyncError("No lesson.manifest.yaml files in path map")

    seen_lesson_slugs: set[str] = set()
    prepared: list[_PreparedLessonSync] = []

    for manifest_path in manifest_repo_paths:
        raw = path_to_content.get(manifest_path)
        if raw is None:
            raise LessonRepoSyncError(
                f"Manifest path missing content: {manifest_path!r}"
            )
        try:
            manifest = parse_lesson_manifest(raw)
        except ManifestValidationError as exc:
            raise LessonRepoSyncError(str(exc)) from exc

        slug = manifest.lesson.slug
        if slug in seen_lesson_slugs:
            raise LessonRepoSyncError(
                f"Duplicate lesson slug across manifests: {slug!r}",
            )
        seen_lesson_slugs.add(slug)

        parts_out: list[tuple[int, str, str, str, int | None, str]] = []
        for ordering, part in enumerate(manifest.parts):
            blob_key = _part_file_key(
                manifest_repo_path=manifest_path,
                part_relative_path=part.path,
            )
            body_md = path_to_content.get(blob_key)
            if body_md is None:
                raise LessonRepoSyncError(
                    f"Referenced markdown missing for lesson {slug!r}: path {blob_key!r}",
                )
            parts_out.append(
                (
                    ordering,
                    part.slug,
                    part.title,
                    part.path,
                    part.estimated_minutes,
                    body_md,
                ),
            )

        badges_out: list[tuple[str, str, int, str | None]] = []
        if manifest.badges:
            for b in manifest.badges:
                badges_out.append((b.slug, b.title, b.points, b.description))

        prepared.append(
            _PreparedLessonSync(
                manifest_repo_path=manifest_path,
                manifest_sha256=sha256(raw.encode("utf-8")).hexdigest(),
                lesson_slug=slug,
                title=manifest.lesson.title,
                summary=manifest.lesson.summary,
                parts=parts_out,
                badges=badges_out,
            ),
        )

    return prepared


def apply_prepared_lesson_sync_to_repo(
    *, session: Session, lesson_repo: LessonRepo, prepared: list[_PreparedLessonSync]
) -> None:
    """Upsert lessons and replace parts under ``lesson_repo`` (phase 2)."""
    existing_manifest_rows = {
        row.manifest_repo_path: row
        for row in session.exec(
            select(LessonManifestSync).where(
                LessonManifestSync.repo_id == lesson_repo.id
            )
        ).all()
    }
    touched_manifest_paths: set[str] = set()

    for item in prepared:
        touched_manifest_paths.add(item.manifest_repo_path)
        lesson = session.exec(
            select(Lesson).where(
                Lesson.repo_id == lesson_repo.id,
                Lesson.slug == item.lesson_slug,
            ),
        ).first()
        if lesson is None:
            lesson = Lesson(
                repo_id=lesson_repo.id,
                slug=item.lesson_slug,
                title=item.title,
                summary=item.summary,
                lesson_sync_generation=1,
            )
            session.add(lesson)
            session.flush()
        else:
            lesson.title = item.title
            lesson.summary = item.summary

        for stale in session.exec(
            select(LessonPart).where(LessonPart.lesson_id == lesson.id),
        ).all():
            session.delete(stale)
        session.flush()

        for ordering, slug, title, path, estimated_minutes, body_md in item.parts:
            session.add(
                LessonPart(
                    lesson_id=lesson.id,
                    ordering=ordering,
                    slug=slug,
                    title=title,
                    path=path,
                    estimated_minutes=estimated_minutes,
                    body_md=body_md,
                ),
            )

        manifest_badge_slugs: set[str] = set()
        for m_badge_slug, b_title, b_points, b_description in item.badges:
            manifest_badge_slugs.add(m_badge_slug)
            full_slug = f"{item.lesson_slug}__{m_badge_slug}"
            if len(full_slug) > 128:
                raise LessonRepoSyncError(
                    f"composed badge slug exceeds 128 characters: {full_slug!r}",
                )
            existing_badge = session.exec(
                select(WorkshopBadgeDefinition).where(
                    WorkshopBadgeDefinition.slug == full_slug
                )
            ).first()
            if existing_badge is None:
                session.add(
                    WorkshopBadgeDefinition(
                        slug=full_slug,
                        title=b_title,
                        description=b_description,
                        points=b_points,
                        lesson_id=lesson.id,
                    )
                )
            else:
                existing_badge.title = b_title
                existing_badge.points = b_points
                existing_badge.description = b_description
                existing_badge.lesson_id = lesson.id
                existing_badge.archived_at = None

        expected_full_slugs = {f"{item.lesson_slug}__{s}" for s in manifest_badge_slugs}
        prefix = f"{item.lesson_slug}__"
        for stale_def in session.exec(
            select(WorkshopBadgeDefinition).where(
                WorkshopBadgeDefinition.lesson_id == lesson.id,
                col(WorkshopBadgeDefinition.slug).like(f"{prefix}%"),
            )
        ).all():
            if stale_def.slug in expected_full_slugs:
                continue
            active_grants = session.exec(
                select(func.count())
                .select_from(WorkshopBadgeGrant)
                .where(
                    WorkshopBadgeGrant.badge_id == stale_def.id,
                    col(WorkshopBadgeGrant.revoked_at).is_(None),
                )
            ).one()
            n_active = int(active_grants or 0)
            if n_active > 0:
                stale_def.archived_at = get_datetime_utc()
                session.add(stale_def)
            else:
                session.delete(stale_def)

        lesson.lesson_sync_generation = lesson.lesson_sync_generation + 1
        session.add(lesson)

        manifest_row = existing_manifest_rows.get(item.manifest_repo_path)
        if manifest_row is None:
            manifest_row = LessonManifestSync(
                repo_id=lesson_repo.id,
                lesson_slug=item.lesson_slug,
                manifest_repo_path=item.manifest_repo_path,
                manifest_sha256=item.manifest_sha256,
            )
        else:
            manifest_row.lesson_slug = item.lesson_slug
            manifest_row.manifest_sha256 = item.manifest_sha256
            manifest_row.synced_at = get_datetime_utc()
        session.add(manifest_row)

    for stale_path, stale_row in existing_manifest_rows.items():
        if stale_path not in touched_manifest_paths:
            session.delete(stale_row)


def sync_lesson_repo_from_path_map(
    *,
    session: Session,
    lesson_repo: LessonRepo,
    path_to_content: dict[str, str],
) -> int:
    """
    Full transactional sync: validate all manifests/files, apply DB updates, set
    ``LessonRepo.health`` and ``last_synced_at``.

    Returns number of lesson rows synced.
    """
    try:
        prepared = prepare_lesson_sync_ops_from_path_map(path_to_content)
        apply_prepared_lesson_sync_to_repo(
            session=session,
            lesson_repo=lesson_repo,
            prepared=prepared,
        )
        lesson_repo.health = "healthy"
        lesson_repo.last_synced_at = get_datetime_utc()
        session.add(lesson_repo)
        session.commit()
        return len(prepared)
    except LessonRepoSyncError:
        session.rollback()
        lesson_repo.health = "unhealthy"
        session.add(lesson_repo)
        session.commit()
        raise
    except Exception:
        session.rollback()
        lesson_repo.health = "unhealthy"
        session.add(lesson_repo)
        session.commit()
        raise
