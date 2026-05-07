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
