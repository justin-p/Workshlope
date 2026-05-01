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
