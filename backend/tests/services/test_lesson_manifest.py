import pytest

from app.services.lesson_manifest import ManifestValidationError, parse_lesson_manifest


def test_parse_manifest_accepts_valid_yaml() -> None:
    payload = """
version: 1
lesson:
  slug: fastapi-workshop-basics
  title: FastAPI Workshop Basics
parts:
  - slug: setup-and-prereqs
    title: Setup and Prerequisites
    path: 01-setup.md
"""
    parsed = parse_lesson_manifest(payload)
    assert parsed.lesson.slug == "fastapi-workshop-basics"
    assert parsed.parts[0].path == "01-setup.md"


def test_parse_manifest_rejects_uppercase_lesson_slug() -> None:
    payload = """
version: 1
lesson:
  slug: FastAPI
  title: X
parts:
  - slug: ok-slug
    title: P
    path: 01-setup.md
"""
    with pytest.raises(ManifestValidationError):
        parse_lesson_manifest(payload)


def test_parse_manifest_rejects_duplicate_part_slug() -> None:
    payload = """
version: 1
lesson:
  slug: lesson-a
  title: Lesson A
parts:
  - slug: dup
    title: First
    path: a.md
  - slug: dup
    title: Second
    path: b.md
"""
    with pytest.raises(ManifestValidationError):
        parse_lesson_manifest(payload)


def test_parse_manifest_rejects_negative_estimated_minutes() -> None:
    payload = """
version: 1
lesson:
  slug: lesson-a
  title: Lesson A
parts:
  - slug: one
    title: Part One
    path: 01-setup.md
    estimated_minutes: -1
"""
    with pytest.raises(ManifestValidationError):
        parse_lesson_manifest(payload)


def test_parse_manifest_rejects_empty_objective_entry() -> None:
    payload = """
version: 1
lesson:
  slug: lesson-a
  title: Lesson A
parts:
  - slug: one
    title: Part One
    path: 01-setup.md
    objectives:
      - ""
"""
    with pytest.raises(ManifestValidationError):
        parse_lesson_manifest(payload)


def test_parse_manifest_rejects_unknown_nested_key() -> None:
    payload = """
version: 1
lesson:
  slug: fastapi-workshop-basics
  title: FastAPI Workshop Basics
parts:
  - slug: setup-and-prereqs
    title: Setup and Prerequisites
    path: 01-setup.md
    unexpected: value
"""
    with pytest.raises(ManifestValidationError):
        parse_lesson_manifest(payload)


def test_parse_manifest_v2_accepts_optional_badges() -> None:
    payload = """
version: 2
lesson:
  slug: lesson-v2
  title: V2
parts:
  - slug: one
    title: One
    path: a.md
badges:
  - slug: finisher
    title: Finished
    points: 10
    description: Completed all parts
"""
    m = parse_lesson_manifest(payload)
    assert m.version == 2
    assert m.badges is not None and len(m.badges) == 1
    assert m.badges[0].slug == "finisher"
    assert m.badges[0].points == 10


def test_parse_manifest_v1_rejects_badges_key() -> None:
    payload = """
version: 1
lesson:
  slug: lesson-a
  title: Lesson A
parts:
  - slug: one
    title: Part One
    path: 01-setup.md
badges: []
"""
    with pytest.raises(
        ManifestValidationError, match="version 1 must not declare badges"
    ):
        parse_lesson_manifest(payload)
