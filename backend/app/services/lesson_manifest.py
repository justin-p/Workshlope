from __future__ import annotations

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class ManifestValidationError(ValueError):
    """Raised when a lesson manifest payload fails validation."""


class LessonMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    summary: str | None = None


class LessonPartMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    path: str
    estimated_minutes: int | None = None
    objectives: list[str] | None = None

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


def parse_lesson_manifest(payload: str) -> LessonManifest:
    try:
        data = yaml.safe_load(payload)
        return LessonManifest.model_validate(data)
    except (yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
        raise ManifestValidationError(str(exc)) from exc
