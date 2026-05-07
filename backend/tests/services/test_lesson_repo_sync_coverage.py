"""Branch coverage for lesson_repo_sync prepare/apply/sync."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models import Lesson, LessonPart, LessonRepo
from app.services.lesson_repo_sync import (
    LessonRepoSyncError,
    _reject_unsafe_repo_path,
    apply_prepared_lesson_sync_to_repo,
    prepare_lesson_sync_ops_from_path_map,
    sync_lesson_repo_from_path_map,
)


def test_reject_unsafe_repo_path_raises_on_empty_string() -> None:
    with pytest.raises(LessonRepoSyncError, match="empty"):
        _reject_unsafe_repo_path("")


def test_prepare_no_manifest_yaml_in_map() -> None:
    with pytest.raises(LessonRepoSyncError, match="No lesson.manifest"):
        prepare_lesson_sync_ops_from_path_map({"README.md": "#"})


def test_prepare_manifest_listed_in_keys_but_get_returns_none() -> None:
    path_map = MagicMock()
    path_map.keys.return_value = ["lessons/x/lesson.manifest.yaml"]
    path_map.get.return_value = None
    with pytest.raises(LessonRepoSyncError, match="missing content"):
        prepare_lesson_sync_ops_from_path_map(path_map)


def test_prepare_root_manifest_uses_part_path_without_parent_prefix() -> None:
    yaml = """version: 1
lesson:
  slug: root-lesson
  title: L
parts:
  - slug: p
    title: P
    path: body.md
"""
    prepared = prepare_lesson_sync_ops_from_path_map(
        {
            "lesson.manifest.yaml": yaml,
            "body.md": "# body",
        },
    )
    assert len(prepared) == 1
    assert prepared[0].lesson_slug == "root-lesson"


def test_prepare_rejects_empty_map() -> None:
    with pytest.raises(LessonRepoSyncError, match="Empty"):
        prepare_lesson_sync_ops_from_path_map({})


def test_prepare_rejects_traversal_in_manifest_path() -> None:
    yaml = """version: 1
lesson:
  slug: t
  title: L
parts:
  - slug: p
    title: P
    path: ok.md
"""
    with pytest.raises(LessonRepoSyncError, match="traversal"):
        prepare_lesson_sync_ops_from_path_map(
            {
                "../lessons/x/lesson.manifest.yaml": yaml,
                "lessons/x/ok.md": "#",
            },
        )


def test_prepare_duplicate_lesson_slug() -> None:
    yaml = """version: 1
lesson:
  slug: dup
  title: L
parts:
  - slug: p
    title: P
    path: z.md
"""
    path_map = {
        "lessons/a/lesson.manifest.yaml": yaml,
        "lessons/a/z.md": "#",
        "lessons/b/lesson.manifest.yaml": yaml,
        "lessons/b/z.md": "#",
    }
    with pytest.raises(LessonRepoSyncError, match="Duplicate"):
        prepare_lesson_sync_ops_from_path_map(path_map)


def test_prepare_wraps_manifest_parse_errors() -> None:
    raw = "{ not: yaml"
    with pytest.raises(LessonRepoSyncError):
        prepare_lesson_sync_ops_from_path_map(
            {
                "lessons/x/lesson.manifest.yaml": raw,
            },
        )


def test_sync_marks_repo_unhealthy_on_unexpected_engine_error() -> None:
    """Exercise generic Exception handler (DB failure during apply)."""

    yaml = """version: 1
lesson:
  slug: one
  title: Lesson
parts:
  - slug: part
    title: Part
    path: body.md
"""
    path_map = {
        "lessons/x/lesson.manifest.yaml": yaml,
        "lessons/x/body.md": "# Hello",
    }
    repo = LessonRepo(
        full_name=f"cov/unhealthy-{uuid.uuid4()}",
        default_branch="main",
        health="healthy",
    )
    with Session(engine) as session:
        session.add(repo)
        session.commit()
        session.refresh(repo)

        with patch(
            "app.services.lesson_repo_sync.apply_prepared_lesson_sync_to_repo",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                sync_lesson_repo_from_path_map(
                    session=session,
                    lesson_repo=repo,
                    path_to_content=path_map,
                )

        session.refresh(repo)
        assert repo.health == "unhealthy"
        session.delete(repo)
        session.commit()


def test_apply_updates_existing_lesson_row() -> None:
    """Cover apply branch that updates title/summary on an existing lesson."""
    yaml = """version: 1
lesson:
  slug: keep
  title: After sync
  summary: S
parts:
  - slug: a
    title: A
    path: a.md
"""
    path_map = {
        "lessons/k/lesson.manifest.yaml": yaml,
        "lessons/k/a.md": "# A",
    }
    repo = LessonRepo(
        full_name=f"cov/apply-update-{uuid.uuid4()}",
        default_branch="main",
        health="healthy",
    )
    with Session(engine) as session:
        session.add(repo)
        session.flush()
        prior = Lesson(
            repo_id=repo.id,
            slug="keep",
            title="Before sync",
            summary=None,
            lesson_sync_generation=1,
        )
        session.add(prior)
        session.flush()
        session.add(
            LessonPart(
                lesson_id=prior.id,
                ordering=0,
                slug="stale",
                title="Stale",
                path="old.md",
                body_md="x",
            ),
        )
        session.commit()

        prepared = prepare_lesson_sync_ops_from_path_map(path_map)
        apply_prepared_lesson_sync_to_repo(
            session=session,
            lesson_repo=repo,
            prepared=prepared,
        )
        session.commit()

        refreshed = session.exec(
            select(Lesson).where(
                Lesson.repo_id == repo.id,
                Lesson.slug == "keep",
            ),
        ).first()
        assert refreshed is not None
        assert refreshed.title == "After sync"

        parts = session.exec(
            select(LessonPart).where(LessonPart.lesson_id == refreshed.id),
        ).all()
        for p in parts:
            session.delete(p)
        session.delete(refreshed)
        session.delete(repo)
        session.commit()
