from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import (
    Item,
    Lesson,
    LessonPart,
    LessonRepo,
    OAuthAccount,
    PendingGitHubLogin,
    SessionInstructor,
    User,
    WorkshopBadgeDefinition,
    WorkshopBadgeGrant,
    WorkshopParticipant,
    WorkshopSession,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        yield session
        statement = delete(Item)
        session.execute(statement)
        statement = delete(SessionInstructor)
        session.execute(statement)
        statement = delete(WorkshopBadgeGrant)
        session.execute(statement)
        statement = delete(WorkshopBadgeDefinition)
        session.execute(statement)
        statement = delete(WorkshopParticipant)
        session.execute(statement)
        statement = delete(WorkshopSession)
        session.execute(statement)
        statement = delete(LessonPart)
        session.execute(statement)
        statement = delete(Lesson)
        session.execute(statement)
        statement = delete(LessonRepo)
        session.execute(statement)
        statement = delete(OAuthAccount)
        session.execute(statement)
        statement = delete(PendingGitHubLogin)
        session.execute(statement)
        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
