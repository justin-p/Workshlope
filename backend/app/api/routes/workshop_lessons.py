import uuid

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Lesson,
    LessonPrerequisite,
    Message,
    User,
    UserPrerequisiteCompletion,
    WorkshopLessonPrerequisiteComplete,
    WorkshopLessonPrerequisiteCreate,
    WorkshopLessonPrerequisitePublic,
    WorkshopLessonPrerequisitesPublic,
)

router = APIRouter(prefix="/workshop/lessons", tags=["workshop-lessons"])


def _require_workshop_lesson_editor(*, current_user: User) -> None:
    if current_user.is_superuser or current_user.is_instructor:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Instructor privileges required",
    )


@router.post(
    "/{lesson_id}/prerequisites", response_model=WorkshopLessonPrerequisitePublic
)
def create_lesson_prerequisite(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    lesson_id: uuid.UUID,
    body: WorkshopLessonPrerequisiteCreate,
) -> WorkshopLessonPrerequisitePublic:
    _require_workshop_lesson_editor(current_user=current_user)
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        )

    row = LessonPrerequisite(
        lesson_id=lesson_id,
        type=body.type,
        title=body.title,
        details=body.details,
        url=body.url,
        ordering=body.ordering,
        required_flag=body.required_flag,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return WorkshopLessonPrerequisitePublic.model_validate(row)


@router.get(
    "/{lesson_id}/prerequisites", response_model=WorkshopLessonPrerequisitesPublic
)
def read_lesson_prerequisites(
    *, session: SessionDep, current_user: CurrentUser, lesson_id: uuid.UUID
) -> WorkshopLessonPrerequisitesPublic:
    _require_workshop_lesson_editor(current_user=current_user)
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        )

    rows = session.exec(
        select(LessonPrerequisite)
        .where(LessonPrerequisite.lesson_id == lesson_id)
        .order_by(col(LessonPrerequisite.ordering))
    ).all()
    return WorkshopLessonPrerequisitesPublic(
        data=[WorkshopLessonPrerequisitePublic.model_validate(row) for row in rows],
        count=len(rows),
    )


@router.post(
    "/{lesson_id}/prerequisites/{prerequisite_id}/complete", response_model=Message
)
def complete_lesson_prerequisite(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    lesson_id: uuid.UUID,
    prerequisite_id: uuid.UUID,
    body: WorkshopLessonPrerequisiteComplete | None = None,
) -> Message:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        )
    prerequisite = session.exec(
        select(LessonPrerequisite).where(
            LessonPrerequisite.id == prerequisite_id,
            LessonPrerequisite.lesson_id == lesson_id,
        )
    ).first()
    if prerequisite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prerequisite not found"
        )

    payload = body or WorkshopLessonPrerequisiteComplete()
    target_user_id = payload.user_id or current_user.id
    if target_user_id != current_user.id:
        _require_workshop_lesson_editor(current_user=current_user)
    target_user = session.get(User, target_user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    completion = session.exec(
        select(UserPrerequisiteCompletion).where(
            UserPrerequisiteCompletion.user_id == target_user_id,
            UserPrerequisiteCompletion.prerequisite_id == prerequisite_id,
        )
    ).first()
    source = "self" if target_user_id == current_user.id else "instructor"
    if completion is None:
        completion = UserPrerequisiteCompletion(
            user_id=target_user_id,
            lesson_id=lesson_id,
            prerequisite_id=prerequisite_id,
            source=source,
        )
    else:
        completion.source = source
    session.add(completion)
    session.commit()
    return Message(message="Prerequisite marked complete")
