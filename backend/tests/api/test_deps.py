import pytest
from fastapi import HTTPException

from app.api.deps import get_current_active_instructor
from app.models import User


def test_get_current_active_instructor_rejects_non_instructor() -> None:
    user = User(
        email="user@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=False,
        is_instructor=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        get_current_active_instructor(user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "The user doesn't have instructor privileges"


def test_get_current_active_instructor_returns_user_when_flag_set() -> None:
    instructor = User(
        email="inst@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=False,
        is_instructor=True,
    )
    assert get_current_active_instructor(instructor) is instructor
