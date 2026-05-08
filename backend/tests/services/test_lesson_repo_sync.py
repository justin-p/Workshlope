"""lesson_repo_sync: path-map validation and Lesson/LessonPart upserts."""

import hashlib
import uuid

import pytest
from sqlmodel import Session, select

from app.models import Lesson, LessonManifestSync, LessonPart, LessonRepo
from app.services.lesson_repo_sync import (
    LessonRepoSyncError,
    sync_lesson_repo_from_path_map,
)


def test_sync_lesson_repo_from_path_map_creates_lesson_and_parts(db: Session) -> None:
    rid = uuid.uuid4()
    repo = LessonRepo(
        full_name=f"org/repo-{rid}",
        default_branch="main",
        health="healthy",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    tree = {
        "lessons/a/lesson.manifest.yaml": """
version: 1
lesson:
  slug: lesson-a
  title: Lesson A
  summary: S
parts:
  - slug: one
    title: Part One
    path: one.md
""",
        "lessons/a/one.md": "# One",
    }

    synced = sync_lesson_repo_from_path_map(
        session=db,
        lesson_repo=repo,
        path_to_content=tree,
    )
    assert synced == 1
    db.refresh(repo)
    assert repo.health == "healthy"
    assert repo.last_synced_at is not None

    lesson = db.exec(select(Lesson).where(Lesson.repo_id == repo.id)).first()
    assert lesson is not None
    assert lesson.slug == "lesson-a"
    assert lesson.title == "Lesson A"
    assert lesson.summary == "S"
    assert lesson.lesson_sync_generation >= 2

    parts = db.exec(select(LessonPart).where(LessonPart.lesson_id == lesson.id)).all()
    assert len(parts) == 1
    assert parts[0].slug == "one"
    assert parts[0].body_md == "# One"


def test_sync_keeps_relative_image_reference_for_runtime_renderer(db: Session) -> None:
    rid = uuid.uuid4()
    full_name = f"org/img-{rid}"
    repo = LessonRepo(
        full_name=full_name,
        default_branch="main",
        health="healthy",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    tree = {
        "lessons/a/lesson.manifest.yaml": """
version: 1
lesson:
  slug: lesson-img
  title: Img
parts:
  - slug: one
    title: One
    path: one.md
""",
        "lessons/a/one.md": "![d](./diagram.png)",
    }

    sync_lesson_repo_from_path_map(
        session=db,
        lesson_repo=repo,
        path_to_content=tree,
    )
    lesson = db.exec(select(Lesson).where(Lesson.repo_id == repo.id)).first()
    assert lesson is not None
    part = db.exec(select(LessonPart).where(LessonPart.lesson_id == lesson.id)).first()
    assert part is not None
    assert part.body_md == "![d](./diagram.png)"


def test_sync_records_manifest_sha_row_and_updates_on_change(db: Session) -> None:
    rid = uuid.uuid4()
    repo = LessonRepo(
        full_name=f"org/manifest-{rid}",
        default_branch="main",
        health="healthy",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    manifest_v1 = """
version: 1
lesson:
  slug: lesson-manifest
  title: Manifest V1
parts:
  - slug: one
    title: Part One
    path: one.md
"""
    tree_v1 = {
        "lessons/a/lesson.manifest.yaml": manifest_v1,
        "lessons/a/one.md": "# One",
    }
    sync_lesson_repo_from_path_map(
        session=db,
        lesson_repo=repo,
        path_to_content=tree_v1,
    )

    row = db.exec(
        select(LessonManifestSync).where(LessonManifestSync.repo_id == repo.id)
    ).first()
    assert row is not None
    assert row.lesson_slug == "lesson-manifest"
    assert row.manifest_repo_path == "lessons/a/lesson.manifest.yaml"
    assert (
        row.manifest_sha256 == hashlib.sha256(manifest_v1.encode("utf-8")).hexdigest()
    )
    assert row.synced_at is not None

    manifest_v2 = manifest_v1.replace("Manifest V1", "Manifest V2")
    tree_v2 = {
        "lessons/a/lesson.manifest.yaml": manifest_v2,
        "lessons/a/one.md": "# One",
    }
    sync_lesson_repo_from_path_map(
        session=db,
        lesson_repo=repo,
        path_to_content=tree_v2,
    )

    rows_after = db.exec(
        select(LessonManifestSync).where(LessonManifestSync.repo_id == repo.id)
    ).all()
    assert len(rows_after) == 1
    assert (
        rows_after[0].manifest_sha256
        == hashlib.sha256(manifest_v2.encode("utf-8")).hexdigest()
    )


def test_sync_duplicate_lesson_slug_marks_repo_unhealthy(db: Session) -> None:
    rid = uuid.uuid4()
    repo = LessonRepo(
        full_name=f"org/dup-{rid}",
        default_branch="main",
        health="healthy",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    dup_manifest = """
version: 1
lesson:
  slug: same-slug
  title: T
parts:
  - slug: p
    title: P
    path: z.md
"""
    tree = {
        "lessons/x/lesson.manifest.yaml": dup_manifest,
        "lessons/x/z.md": "# X",
        "lessons/y/lesson.manifest.yaml": dup_manifest.replace(
            "same-slug", "same-slug"
        ),
        "lessons/y/z.md": "# Y",
    }

    with pytest.raises(LessonRepoSyncError):
        sync_lesson_repo_from_path_map(
            session=db, lesson_repo=repo, path_to_content=tree
        )

    db.refresh(repo)
    assert repo.health == "unhealthy"


def test_sync_missing_part_file_marks_repo_unhealthy(db: Session) -> None:
    rid = uuid.uuid4()
    repo = LessonRepo(
        full_name=f"org/miss-{rid}",
        default_branch="main",
        health="healthy",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    tree = {
        "lessons/a/lesson.manifest.yaml": """
version: 1
lesson:
  slug: lesson-a
  title: Lesson A
parts:
  - slug: one
    title: Part One
    path: one.md
""",
    }

    with pytest.raises(LessonRepoSyncError):
        sync_lesson_repo_from_path_map(
            session=db, lesson_repo=repo, path_to_content=tree
        )

    db.refresh(repo)
    assert repo.health == "unhealthy"
