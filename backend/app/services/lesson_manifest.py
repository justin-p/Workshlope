from __future__ import annotations

import re

import yaml  # type: ignore[import-untyped]
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from typing_extensions import Self

_KEBAB_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ManifestValidationError(ValueError):
    """Raised when a lesson manifest payload fails validation."""


class LessonMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str = Field(min_length=1)
    summary: str | None = None

    @field_validator("slug")
    @classmethod
    def slug_must_be_kebab_case(cls, value: str) -> str:
        if not _KEBAB_SLUG_RE.fullmatch(value):
            raise ValueError(
                "slug must be lowercase kebab-case (letters, digits, single hyphens)"
            )
        return value


class LessonPartMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str = Field(min_length=1)
    path: str
    estimated_minutes: int | None = Field(default=None, ge=0)
    objectives: list[str] | None = None

    @field_validator("slug")
    @classmethod
    def slug_must_be_kebab_case(cls, value: str) -> str:
        if not _KEBAB_SLUG_RE.fullmatch(value):
            raise ValueError(
                "slug must be lowercase kebab-case (letters, digits, single hyphens)"
            )
        return value

    @field_validator("objectives")
    @classmethod
    def objectives_must_be_nonempty_strings(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "objectives entries must be non-empty strings after trimming"
                )
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if value.startswith("/"):
            raise ValueError("path must be relative")
        if ".." in value or "\\" in value:
            raise ValueError("path contains unsafe traversal characters")
        if not value.endswith(".md"):
            raise ValueError("path must end with .md")
        return value


class LessonManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    lesson: LessonMeta
    parts: list[LessonPartMeta]

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("version must be 1")
        return value

    @field_validator("parts")
    @classmethod
    def validate_parts_non_empty(
        cls, value: list[LessonPartMeta]
    ) -> list[LessonPartMeta]:
        if not value:
            raise ValueError("parts must contain at least one entry")
        return value

    @model_validator(mode="after")
    def part_slugs_unique_within_lesson(self) -> Self:
        slugs = [p.slug for p in self.parts]
        if len(slugs) != len(set(slugs)):
            raise ValueError("duplicate part slug within the same lesson")
        return self


def parse_lesson_manifest(payload: str) -> LessonManifest:
    try:
        data = yaml.safe_load(payload)
        return LessonManifest.model_validate(data)
    except (yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
        raise ManifestValidationError(str(exc)) from exc
