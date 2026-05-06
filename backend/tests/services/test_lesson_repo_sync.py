"""lesson_repo_sync: path-map validation and Lesson/LessonPart upserts."""

import uuid

import pytest
from sqlmodel import Session, select

from app.models import Lesson, LessonPart, LessonRepo
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
