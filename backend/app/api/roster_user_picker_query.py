"""Shared instructor user browse/search for workshop roster pickers."""

from sqlalchemy import String, cast, literal, or_
from sqlalchemy.sql import func as sa_func
from sqlmodel import Session, func, select

from app.models import (
    User,
    WorkshopRosterUserPickerPublic,
    WorkshopRosterUserPickerRowPublic,
)

ROSTER_PICKER_MIN_Q_LEN = 2
ROSTER_PICKER_DEFAULT_LIMIT = 25
ROSTER_PICKER_MAX_LIMIT = 100


def workshop_roster_user_picker_public(
    session: Session,
    *,
    q: str | None,
    skip: int,
    limit: int,
) -> WorkshopRosterUserPickerPublic:
    """Paginated user list for roster pickers; optional pg_trgm-ranked search."""
    q_stripped = (q or "").strip()
    if q_stripped:
        if len(q_stripped) < ROSTER_PICKER_MIN_Q_LEN:
            raise ValueError(
                f"Search query must be at least {ROSTER_PICKER_MIN_Q_LEN} characters"
            )
        email_c = cast(User.email, String)
        name_c = func.coalesce(cast(User.full_name, String), "")
        q_lit = literal(q_stripped)
        sim_e = sa_func.similarity(email_c, q_lit)
        sim_n = sa_func.similarity(name_c, q_lit)
        match_expr = sa_func.greatest(sim_e, sim_n)
        cond = or_(email_c.op("%")(q_lit), name_c.op("%")(q_lit))
        count_val = session.exec(
            select(func.count()).select_from(User).where(cond)
        ).one()
        stmt = (
            select(User, match_expr.label("match_score"))
            .where(cond)
            .order_by(match_expr.desc(), User.email)
            .offset(skip)
            .limit(limit)
        )
        rows = session.exec(stmt).all()
        data = [
            WorkshopRosterUserPickerRowPublic(
                user_id=user.id,
                email=str(user.email),
                full_name=user.full_name,
                is_superuser=user.is_superuser,
                is_instructor=user.is_instructor,
                is_active=user.is_active,
                match_score=float(score) if score is not None else None,
            )
            for user, score in rows
        ]
        return WorkshopRosterUserPickerPublic(data=data, count=int(count_val))

    count_val = session.exec(select(func.count()).select_from(User)).one()
    browse_stmt = select(User).order_by(User.email).offset(skip).limit(limit)
    users = session.exec(browse_stmt).all()
    data = [
        WorkshopRosterUserPickerRowPublic(
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            is_superuser=user.is_superuser,
            is_instructor=user.is_instructor,
            is_active=user.is_active,
            match_score=None,
        )
        for user in users
    ]
    return WorkshopRosterUserPickerPublic(data=data, count=int(count_val))
