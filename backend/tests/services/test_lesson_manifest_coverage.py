"""Exercise lesson_manifest validators for full branch coverage."""

import pytest

from app.services.lesson_manifest import ManifestValidationError, parse_lesson_manifest


def test_part_slug_invalid_kebab() -> None:
    raw = """version: 1
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: Bad_Slug
    title: P
    path: x.md
"""
    with pytest.raises(ManifestValidationError):
        parse_lesson_manifest(raw)


def test_part_objectives_empty_string_rejected() -> None:
    raw = """version: 1
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: one
    title: P
    path: x.md
    objectives: [" "]
"""
    with pytest.raises(ManifestValidationError):
        parse_lesson_manifest(raw)


@pytest.mark.parametrize(
    "path,expect",
    [
        ("/abs.md", "relative"),
        ("../x.md", "traversal"),
        ("x.txt", ".md"),
    ],
)
def test_part_path_validation(path: str, expect: str) -> None:
    raw = f"""version: 1
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: one
    title: P
    path: {path}
"""
    with pytest.raises(ManifestValidationError, match=expect):
        parse_lesson_manifest(raw)


def test_version_must_be_one() -> None:
    raw = """version: 2
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: one
    title: P
    path: x.md
"""
    with pytest.raises(ManifestValidationError, match="version must be 1 or 2"):
        parse_lesson_manifest(raw)


def test_parts_must_be_non_empty() -> None:
    raw = """version: 1
lesson:
  slug: ok-lesson
  title: T
parts: []
"""
    with pytest.raises(ManifestValidationError, match="at least one"):
        parse_lesson_manifest(raw)


def test_part_objectives_omitted_is_valid() -> None:
    raw = """version: 1
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: one
    title: P
    path: x.md
"""
    parsed = parse_lesson_manifest(raw)
    assert parsed.parts[0].objectives is None


def test_part_objectives_explicit_null_is_valid() -> None:
    raw = """version: 1
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: one
    title: P
    path: x.md
    objectives: null
"""
    parsed = parse_lesson_manifest(raw)
    assert parsed.parts[0].objectives is None


def test_part_objectives_nonempty_strings_accepted() -> None:
    raw = """version: 1
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: one
    title: P
    path: x.md
    objectives: ["Read the docs"]
"""
    parsed = parse_lesson_manifest(raw)
    assert parsed.parts[0].objectives == ["Read the docs"]


def test_duplicate_part_slugs_rejected() -> None:
    raw = """version: 1
lesson:
  slug: ok-lesson
  title: T
parts:
  - slug: dup
    title: A
    path: a.md
  - slug: dup
    title: B
    path: b.md
"""
    with pytest.raises(ManifestValidationError, match="duplicate"):
        parse_lesson_manifest(raw)
