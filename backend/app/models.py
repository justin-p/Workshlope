import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import EmailStr
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    is_instructor: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore[assignment]


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# ---------------------------------------------------------------------------
# Workshop lesson sync models
# ---------------------------------------------------------------------------


class LessonRepo(SQLModel, table=True):
    __tablename__ = "lesson_repo"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    full_name: str = Field(max_length=255, unique=True, index=True)
    default_branch: str = Field(default="main", max_length=255)
    health: str = Field(default="healthy", max_length=32)
    last_synced_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    lessons: list["Lesson"] = Relationship(back_populates="repo", cascade_delete=True)


class Lesson(SQLModel, table=True):
    __tablename__ = "lesson"
    __table_args__ = (UniqueConstraint("repo_id", "slug", name="uq_lesson_repo_slug"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo_id: uuid.UUID = Field(
        foreign_key="lesson_repo.id", nullable=False, ondelete="CASCADE"
    )
    slug: str = Field(max_length=255)
    title: str = Field(max_length=255)
    summary: str | None = Field(default=None, max_length=2000)
    lesson_sync_generation: int = Field(default=1)
    repo: LessonRepo | None = Relationship(back_populates="lessons")
    parts: list["LessonPart"] = Relationship(
        back_populates="lesson", cascade_delete=True
    )


class LessonPart(SQLModel, table=True):
    __tablename__ = "lesson_part"
    __table_args__ = (
        UniqueConstraint("lesson_id", "slug", name="uq_lesson_part_slug"),
        UniqueConstraint("lesson_id", "ordering", name="uq_lesson_part_ordering"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lesson_id: uuid.UUID = Field(
        foreign_key="lesson.id", nullable=False, ondelete="CASCADE"
    )
    ordering: int = Field(ge=0)
    slug: str = Field(max_length=255)
    title: str = Field(max_length=255)
    path: str = Field(max_length=512)
    body_md: str = Field(default="")
    lesson: Lesson | None = Relationship(back_populates="parts")


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# GitHub OAuth integration (pending-approval linking)
# ---------------------------------------------------------------------------


class OAuthAccount(SQLModel, table=True):
    __tablename__ = "oauth_account"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_oauth_provider_account",
        ),
        UniqueConstraint(
            "user_id",
            "provider",
            name="uq_oauth_user_provider",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    provider: str = Field(max_length=32, index=True)
    provider_account_id: str = Field(max_length=255)
    provider_login: str | None = Field(default=None, max_length=255)
    linked_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    linked_by_user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        nullable=True,
    )


class OAuthAccountPublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    provider: str
    provider_account_id: str
    provider_login: str | None = None
    linked_at: datetime | None = None


class PendingGitHubLogin(SQLModel, table=True):
    __tablename__ = "pending_github_login"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_pending_github_provider_account",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider: str = Field(max_length=32, index=True)
    provider_account_id: str = Field(max_length=255)
    provider_login: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=512)
    first_seen_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    last_seen_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    attempt_count: int = Field(default=1)


class PendingGitHubLoginPublic(SQLModel):
    id: uuid.UUID
    provider: str
    provider_account_id: str
    provider_login: str | None = None
    email: str | None = None
    full_name: str | None = None
    avatar_url: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    attempt_count: int


class PendingGitHubLoginsPublic(SQLModel):
    data: list[PendingGitHubLoginPublic]
    count: int


class ApprovePendingRequest(SQLModel):
    """Approve a pending GitHub login.

    Exactly one of ``user_id`` or ``create_user`` must be provided.
    """

    user_id: uuid.UUID | None = None
    create_user: bool = False


class GitHubBridgeRequest(SQLModel):
    bridge_token: str


class BridgeResponse(SQLModel):
    """Discriminated response from the GitHub bridge endpoint.

    - ``status="signed_in"`` -> ``access_token`` and ``token_type`` are set,
      ``pending_id`` is null.
    - ``status="pending_approval"`` -> ``pending_id`` is set, token fields null.
    """

    status: Literal["signed_in", "pending_approval"]
    access_token: str | None = None
    token_type: str | None = None
    pending_id: uuid.UUID | None = None
