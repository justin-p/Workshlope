import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import get_password_hash
from app.models import (
    Lesson,
    LessonPart,
    LessonPrerequisite,
    LessonRepo,
    SessionInstructor,
    User,
    UserPublic,
    WorkshopParticipant,
    WorkshopSession,
)

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    is_verified: bool = False
    is_instructor: bool = False


@router.post("/users/", response_model=UserPublic)
def create_user(user_in: PrivateUserCreate, session: SessionDep) -> Any:
    """
    Create a new user.
    """

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        is_instructor=user_in.is_instructor,
    )

    session.add(user)
    session.commit()

    return user


class PrivateWorkshopE2ELiveSessionResponse(BaseModel):
    session_id: uuid.UUID


@router.post(
    "/workshop/e2e-live-session/",
    response_model=PrivateWorkshopE2ELiveSessionResponse,
)
def bootstrap_e2e_workshop_live_session(
    *,
    session: SessionDep,
    participant_email: Annotated[EmailStr | None, Query()] = None,
    omit_participant_seat: Annotated[bool, Query()] = False,
    initial_status: Annotated[Literal["live", "scheduled"], Query()] = "live",
    with_incomplete_required_prerequisite: Annotated[bool, Query()] = False,
) -> PrivateWorkshopE2ELiveSessionResponse:
    """Create a live workshop session with lesson parts for local E2E only.

    Roster ``FIRST_SUPERUSER`` (or ``participant_email``) as trainee + session
    instructor. Exposed only when ``ENVIRONMENT == local`` via ``api_router``.
    Pass ``omit_participant_seat=true`` to roster the user **only** as an
    instructor (no ``WorkshopParticipant`` row), so ``ws-ticket`` yields the
    **instructor** role while the frontend skips ``POST …/enter`` for that flow.
    Pass ``initial_status=scheduled`` to exercise instructor start flows.
    Pass ``with_incomplete_required_prerequisite=true`` to add one **required**
    lesson prerequisite with **no** completion row for the rostered trainee
    (participant flows / Playwright pre-work UI).

    When ``participant_email`` is set and differs from ``FIRST_SUPERUSER``, the
    trainee is rostered **only** as a participant and **``FIRST_SUPERUSER``** is
    the sole lead instructor (avoids dual instructor+participant seats on the
    trainee, which breaks HTTP ``view: participant`` and complicates WS E2E).
    """
    email = participant_email or settings.FIRST_SUPERUSER
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant user not found",
        )

    su = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    distinct_trainee = (
        participant_email is not None
        and str(participant_email).lower() != str(settings.FIRST_SUPERUSER).lower()
    )

    sid = uuid.uuid4()
    repo = LessonRepo(
        full_name=f"e2e/{sid}",
        default_branch="main",
        health="healthy",
    )
    session.add(repo)
    session.commit()
    session.refresh(repo)

    lesson = Lesson(
        repo_id=repo.id,
        slug=f"e2e-lesson-{sid}",
        title="E2E Lesson",
        lesson_sync_generation=1,
    )
    session.add(lesson)
    session.commit()
    session.refresh(lesson)

    session.add(
        LessonPart(
            lesson_id=lesson.id,
            ordering=0,
            slug=f"part-0-{sid}",
            title="Part 0",
            path="01-part-0.md",
            body_md="# Part 0",
        )
    )
    session.add(
        LessonPart(
            lesson_id=lesson.id,
            ordering=1,
            slug=f"part-1-{sid}",
            title="Part 1",
            path="02-part-1.md",
            body_md="# Part 1",
        )
    )

    if with_incomplete_required_prerequisite:
        session.add(
            LessonPrerequisite(
                lesson_id=lesson.id,
                type="reading",
                title="E2E required pre-read",
                details="Complete this item in E2E to clear the banner.",
                ordering=0,
                required_flag=True,
            )
        )

    workshop_session = WorkshopSession(
        id=sid,
        lesson_id=lesson.id,
        status=initial_status,
        created_at=datetime.now(timezone.utc),
    )
    session.add(workshop_session)
    if not omit_participant_seat:
        session.add(
            WorkshopParticipant(
                session_id=sid,
                user_id=user.id,
                invited_at=datetime.now(timezone.utc),
                joined_at=datetime.now(timezone.utc),
            )
        )
    if omit_participant_seat:
        session.add(
            SessionInstructor(
                session_id=sid,
                user_id=user.id,
                role="lead",
            )
        )
    elif distinct_trainee:
        if su is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="FIRST_SUPERUSER missing for distinct-trainee E2E bootstrap",
            )
        session.add(
            SessionInstructor(
                session_id=sid,
                user_id=su.id,
                role="lead",
            )
        )
    else:
        session.add(
            SessionInstructor(
                session_id=sid,
                user_id=user.id,
                role="lead",
            )
        )
    session.commit()

    return PrivateWorkshopE2ELiveSessionResponse(session_id=sid)
