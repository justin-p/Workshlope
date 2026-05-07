import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import ConfigDict, EmailStr
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, UniqueConstraint
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


class GithubAppInstallation(SQLModel, table=True):
    """GitHub App installation as reported by installation webhooks."""

    __tablename__ = "github_app_installation"

    id: int = Field(
        sa_column=Column(BigInteger(), primary_key=True, autoincrement=False)
    )
    account_id: int = Field(sa_column=Column(BigInteger(), nullable=False))
    account_login: str = Field(max_length=255, index=True)
    account_type: str = Field(max_length=64)
    target_type: str = Field(max_length=64)
    repository_selection: str | None = Field(default=None, max_length=64)
    app_slug: str | None = Field(default=None, max_length=255)
    suspended_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    repositories: list["GithubInstallationRepository"] = Relationship(
        back_populates="installation",
        cascade_delete=True,
    )
    lesson_repos: list["LessonRepo"] = Relationship(back_populates="installation")


class GithubInstallationRepository(SQLModel, table=True):
    """Repository full_name values currently granted to an installation."""

    __tablename__ = "github_installation_repository"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "full_name",
            name="uq_github_installation_repository_full_name",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    installation_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("github_app_installation.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    full_name: str = Field(max_length=255, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    installation: GithubAppInstallation | None = Relationship(
        back_populates="repositories",
    )


class GithubWebhookDelivery(SQLModel, table=True):
    """Records ``X-GitHub-Delivery`` ids so webhook side effects run at most once."""

    __tablename__ = "github_webhook_delivery"

    delivery_id: str = Field(primary_key=True, max_length=128)
    github_event: str = Field(default="", max_length=128)
    received_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


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
    github_installation_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("github_app_installation.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    installation: GithubAppInstallation | None = Relationship(
        back_populates="lesson_repos",
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


class WorkshopSession(SQLModel, table=True):
    __tablename__ = "workshop_session"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lesson_id: uuid.UUID = Field(
        foreign_key="lesson.id", nullable=False, ondelete="CASCADE"
    )
    status: str = Field(default="scheduled", max_length=32)
    current_part_index: int = Field(default=0, ge=0)
    current_part_slug: str | None = Field(default=None, max_length=255)
    part_generation: int = Field(default=1, ge=1)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class WorkshopParticipant(SQLModel, table=True):
    __tablename__ = "workshop_participant"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_workshop_participant_seat"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        foreign_key="workshop_session.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    invited_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    joined_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    live_status: str = Field(default="busy", max_length=16)
    removed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class SessionInstructor(SQLModel, table=True):
    __tablename__ = "session_instructor"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_session_instructor_seat"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        foreign_key="workshop_session.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    role: str = Field(default="co_instructor", max_length=32)
    assigned_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    removed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class LessonPrerequisite(SQLModel, table=True):
    __tablename__ = "lesson_prerequisite"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "ordering", name="uq_lesson_prerequisite_ordering"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lesson_id: uuid.UUID = Field(
        foreign_key="lesson.id", nullable=False, ondelete="CASCADE"
    )
    type: str = Field(max_length=32, default="task")
    title: str = Field(max_length=255)
    details: str | None = Field(default=None, max_length=1024)
    url: str | None = Field(default=None, max_length=1024)
    ordering: int = Field(default=0, ge=0)
    required_flag: bool = True


class UserPrerequisiteCompletion(SQLModel, table=True):
    __tablename__ = "user_prerequisite_completion"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "prerequisite_id",
            name="uq_user_prerequisite_completion",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    lesson_id: uuid.UUID = Field(
        foreign_key="lesson.id", nullable=False, ondelete="CASCADE"
    )
    prerequisite_id: uuid.UUID = Field(
        foreign_key="lesson_prerequisite.id", nullable=False, ondelete="CASCADE"
    )
    completed_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    source: str = Field(default="self", max_length=32)


class WorkshopSessionTimer(SQLModel, table=True):
    __tablename__ = "workshop_session_timer"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_workshop_session_timer_session"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        foreign_key="workshop_session.id", nullable=False, ondelete="CASCADE"
    )
    status: str = Field(default="inactive", max_length=16)
    mode: str | None = Field(default=None, max_length=16)
    target_seconds: int | None = Field(default=None, ge=1, le=86_400)
    started_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    paused_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class WorkshopSessionTimerEvent(SQLModel, table=True):
    __tablename__ = "workshop_session_timer_event"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        foreign_key="workshop_session.id", nullable=False, ondelete="CASCADE"
    )
    actor_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    action: str = Field(max_length=16)
    mode: str | None = Field(default=None, max_length=16)
    target_seconds: int | None = Field(default=None, ge=1, le=86_400)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class WorkshopBadgeDefinition(SQLModel, table=True):
    __tablename__ = "workshop_badge_definition"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=64, unique=True, index=True)
    title: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    points: int = Field(default=1, ge=0, le=1000)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class WorkshopBadgeGrant(SQLModel, table=True):
    __tablename__ = "workshop_badge_grant"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "user_id", "badge_id", name="uq_workshop_badge_grant_once"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        foreign_key="workshop_session.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    badge_id: uuid.UUID = Field(
        foreign_key="workshop_badge_definition.id", nullable=False, ondelete="CASCADE"
    )
    granted_by_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    granted_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    revoked_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    revoked_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    revoked_reason: str | None = Field(default=None, max_length=255)


class WorkshopSessionListItem(SQLModel):
    """Minimal session row for dashboard lists — no roster, no peer data."""

    id: uuid.UUID
    status: str
    part_generation: int
    lesson_id: uuid.UUID
    lesson_title: str
    lesson_slug: str
    my_role: Literal["participant", "instructor"] | None = Field(
        default=None,
        description="Trainee/participant vs instructor roster seat; ``null`` when superuser is not seated on this session.",
    )
    blocked_required_prereq_count: int | None = Field(
        default=None,
        ge=0,
        description="Roster trainees still missing at least one required prerequisite; only included for instructor/admin visibility.",
    )


class WorkshopSessionsPublic(SQLModel):
    data: list[WorkshopSessionListItem]
    count: int


class WorkshopSessionUpsertMember(SQLModel):
    """Assign a user as participant or instructor for one session."""

    user_id: uuid.UUID
    role: Literal["participant", "instructor"]
    instructor_role: str = Field(default="co_instructor", max_length=32)


class WorkshopParticipantPatch(SQLModel):
    """Instructor override fields for a participant seat."""

    live_status: Literal["busy", "done"] | None = None
    joined_at: datetime | None = None
    finished_at: datetime | None = None


class WorkshopSessionInstructorSeatRoleUpdate(SQLModel):
    """Update an active instructor seat's role (e.g. co_instructor → lead)."""

    user_id: uuid.UUID
    role: str = Field(max_length=32)


class WorkshopSessionPatch(SQLModel):
    """Session-level PATCH body; at least one field must be present in the request."""

    status: Literal["live", "paused", "ended"] | None = None
    instructor_seat: WorkshopSessionInstructorSeatRoleUpdate | None = None
    primary_instructor_user_id: uuid.UUID | None = None
    remove_instructor_user_id: uuid.UUID | None = None


class WorkshopLessonPrerequisiteCreate(SQLModel):
    type: str = Field(default="task", max_length=32)
    title: str = Field(max_length=255)
    details: str | None = Field(default=None, max_length=1024)
    url: str | None = Field(default=None, max_length=1024)
    ordering: int = Field(default=0, ge=0)
    required_flag: bool = True


class WorkshopLessonPrerequisitePatch(SQLModel):
    type: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=255)
    details: str | None = Field(default=None, max_length=1024)
    url: str | None = Field(default=None, max_length=1024)
    ordering: int | None = Field(default=None, ge=0)
    required_flag: bool | None = None


class WorkshopLessonPrerequisitePublic(SQLModel):
    id: uuid.UUID
    lesson_id: uuid.UUID
    type: str
    title: str
    details: str | None = None
    url: str | None = None
    ordering: int
    required_flag: bool


class WorkshopLessonPrerequisitesPublic(SQLModel):
    data: list[WorkshopLessonPrerequisitePublic]
    count: int


class WorkshopLessonPrerequisiteMyPublic(SQLModel):
    id: uuid.UUID
    lesson_id: uuid.UUID
    type: str
    title: str
    details: str | None = None
    url: str | None = None
    ordering: int
    required_flag: bool
    is_completed: bool
    completed_at: datetime | None = None
    source: str | None = None


class WorkshopLessonPrerequisitesMyPublic(SQLModel):
    data: list[WorkshopLessonPrerequisiteMyPublic]
    count: int


class WorkshopLessonPrerequisiteGapPublic(SQLModel):
    """Trainee prerequisite gap for instructor cohort views (scoped to a workshop session roster)."""

    user_id: uuid.UUID
    email: str
    full_name: str | None = None
    incomplete_required_prerequisites: list[WorkshopLessonPrerequisitePublic]


class WorkshopLessonPrerequisiteGapsPublic(SQLModel):
    """Users on the session roster who still owe at least one *required* prerequisite."""

    data: list[WorkshopLessonPrerequisiteGapPublic]
    count: int


class WorkshopLessonPrerequisiteAggregatePublic(SQLModel):
    """Session roster completion counts per prerequisite definition (no per-user identity)."""

    prerequisite: WorkshopLessonPrerequisitePublic
    roster_count: int = Field(ge=0, description="Active roster trainee seats.")
    completed_count: int = Field(
        ge=0, description="Roster trainees with a completion row for this prerequisite."
    )


class WorkshopLessonPrerequisiteAggregatesPublic(SQLModel):
    data: list[WorkshopLessonPrerequisiteAggregatePublic]
    count: int


class WorkshopLessonPrerequisiteComplete(SQLModel):
    user_id: uuid.UUID | None = None


class WorkshopLessonPartBrief(SQLModel):
    """Lesson part metadata for workshop session screens (body omitted)."""

    id: uuid.UUID
    ordering: int
    slug: str
    title: str
    body_html: str | None = None


class WorkshopSessionTimerStart(SQLModel):
    mode: Literal["countdown", "countup"] = "countdown"
    target_seconds: int | None = Field(default=None, ge=1, le=86_400)


class WorkshopSessionTimerPublic(SQLModel):
    session_id: uuid.UUID
    status: Literal["inactive", "running", "paused"]
    mode: Literal["countdown", "countup"] | None = None
    target_seconds: int | None = None
    started_at: datetime | None = None
    paused_at: datetime | None = None
    elapsed_seconds: int | None = None
    remaining_seconds: int | None = None


class WorkshopSessionTimerEventPublic(SQLModel):
    id: uuid.UUID
    session_id: uuid.UUID
    actor_user_id: uuid.UUID
    action: Literal["start", "pause", "resume", "stop"]
    mode: Literal["countdown", "countup"] | None = None
    target_seconds: int | None = None
    created_at: datetime | None = None


class WorkshopSessionTimerEventsPublic(SQLModel):
    data: list[WorkshopSessionTimerEventPublic]
    count: int


class WorkshopBadgeDefinitionCreate(SQLModel):
    slug: str = Field(max_length=64)
    title: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    points: int = Field(default=1, ge=0, le=1000)


class WorkshopBadgeDefinitionPublic(SQLModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str | None = None
    points: int


class WorkshopBadgeDefinitionsPublic(SQLModel):
    data: list[WorkshopBadgeDefinitionPublic]
    count: int


class WorkshopBadgeGrantRequest(SQLModel):
    user_id: uuid.UUID
    badge_id: uuid.UUID


class WorkshopBadgeRevokeRequest(SQLModel):
    user_id: uuid.UUID
    badge_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=255)


class WorkshopSessionLeaderboardRowPublic(SQLModel):
    user_id: uuid.UUID
    total_points: int = Field(ge=0)
    badge_count: int = Field(ge=0)


class WorkshopSessionLeaderboardPublic(SQLModel):
    data: list[WorkshopSessionLeaderboardRowPublic]
    count: int


class WorkshopSessionCorePublic(SQLModel):
    id: uuid.UUID
    status: str
    current_part_index: int
    current_part_slug: str | None
    part_generation: int
    created_at: datetime | None


class WorkshopLessonSummaryPublic(SQLModel):
    id: uuid.UUID
    title: str
    slug: str


class WorkshopParticipantSelfPublic(SQLModel):
    """Caller’s own trainee seat snapshot (participant view only)."""

    invited_at: datetime | None
    joined_at: datetime | None
    finished_at: datetime | None
    live_status: str


class WorkshopSessionPublicParticipant(SQLModel):
    """Trainee-visible session detail — lesson + parts + self only (no roster)."""

    model_config = ConfigDict(populate_by_name=True)  # type: ignore[assignment]

    view: Literal["participant"] = "participant"
    session: WorkshopSessionCorePublic
    lesson: WorkshopLessonSummaryPublic
    parts: list[WorkshopLessonPartBrief]
    participant_self: WorkshopParticipantSelfPublic = Field(
        serialization_alias="self",
        validation_alias="self",
    )


class WorkshopRosterParticipantRowPublic(SQLModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    avatar_url: str | None = None
    invited_at: datetime | None
    joined_at: datetime | None
    finished_at: datetime | None
    live_status: str


class WorkshopRosterInstructorRowPublic(SQLModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    avatar_url: str | None = None
    role: str
    assigned_at: datetime | None


class WorkshopSessionPublicInstructor(SQLModel):
    """Instructor-visible session detail with roster."""

    view: Literal["instructor"] = "instructor"
    session: WorkshopSessionCorePublic
    lesson: WorkshopLessonSummaryPublic
    parts: list[WorkshopLessonPartBrief]
    participants: list[WorkshopRosterParticipantRowPublic]
    instructors: list[WorkshopRosterInstructorRowPublic]


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
