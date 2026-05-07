import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, col, select

from app.core.security import get_password_hash, verify_password
from app.models import (
    Item,
    ItemCreate,
    OAuthAccount,
    PendingGitHubLogin,
    User,
    UserCreate,
    UserUpdate,
)


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


# ---------------------------------------------------------------------------
# OAuth accounts (GitHub) and pending logins
# ---------------------------------------------------------------------------


def get_oauth_account(
    *, session: Session, provider: str, provider_account_id: str
) -> OAuthAccount | None:
    statement = select(OAuthAccount).where(
        OAuthAccount.provider == provider,
        OAuthAccount.provider_account_id == provider_account_id,
    )
    return session.exec(statement).first()


def get_oauth_account_for_user(
    *, session: Session, user_id: uuid.UUID, provider: str
) -> OAuthAccount | None:
    statement = select(OAuthAccount).where(
        OAuthAccount.user_id == user_id,
        OAuthAccount.provider == provider,
    )
    return session.exec(statement).first()


def create_oauth_account(
    *,
    session: Session,
    user_id: uuid.UUID,
    provider: str,
    provider_account_id: str,
    provider_login: str | None = None,
    avatar_url: str | None = None,
    linked_by_user_id: uuid.UUID | None = None,
) -> OAuthAccount:
    db_obj = OAuthAccount(
        user_id=user_id,
        provider=provider,
        provider_account_id=str(provider_account_id),
        provider_login=provider_login,
        avatar_url=avatar_url,
        linked_by_user_id=linked_by_user_id,
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def sync_linked_github_oauth_from_bridge_claims(
    *,
    session: Session,
    account: OAuthAccount,
    provider_login: object | None,
    avatar_url: object | None,
) -> OAuthAccount:
    """Update stored GitHub profile fields from a verified bridge token (linked user)."""
    if account.provider != "github":
        return account
    changed = False
    if isinstance(provider_login, str):
        login = provider_login.strip()[:255]
        if login and account.provider_login != login:
            account.provider_login = login
            changed = True
    if isinstance(avatar_url, str):
        avatar = avatar_url.strip()[:512]
        if avatar and account.avatar_url != avatar:
            account.avatar_url = avatar
            changed = True
    if changed:
        session.add(account)
        session.commit()
        session.refresh(account)
    return account


def delete_oauth_account_for_user(
    *, session: Session, user_id: uuid.UUID, provider: str
) -> bool:
    existing = get_oauth_account_for_user(
        session=session, user_id=user_id, provider=provider
    )
    if not existing:
        return False
    session.delete(existing)
    session.commit()
    return True


def get_pending_github_login(
    *, session: Session, provider: str, provider_account_id: str
) -> PendingGitHubLogin | None:
    statement = select(PendingGitHubLogin).where(
        PendingGitHubLogin.provider == provider,
        PendingGitHubLogin.provider_account_id == provider_account_id,
    )
    return session.exec(statement).first()


def get_pending_github_login_by_id(
    *, session: Session, pending_id: uuid.UUID
) -> PendingGitHubLogin | None:
    return session.get(PendingGitHubLogin, pending_id)


def list_pending_github_logins(
    *, session: Session, skip: int = 0, limit: int = 100
) -> tuple[list[PendingGitHubLogin], int]:
    count_stmt = select(PendingGitHubLogin)
    count = len(session.exec(count_stmt).all())
    statement = (
        select(PendingGitHubLogin)
        .order_by(col(PendingGitHubLogin.last_seen_at).desc())
        .offset(skip)
        .limit(limit)
    )
    rows = list(session.exec(statement).all())
    return rows, count


def upsert_pending_github_login(
    *,
    session: Session,
    provider: str,
    provider_account_id: str,
    provider_login: str | None = None,
    email: str | None = None,
    full_name: str | None = None,
    avatar_url: str | None = None,
) -> PendingGitHubLogin:
    """Insert or update a pending GitHub login record for first-time logins.

    Looks up by (provider, provider_account_id). If found, increments
    ``attempt_count`` and refreshes profile fields + ``last_seen_at``. If not,
    creates a new pending row.
    """
    now = datetime.now(timezone.utc)
    existing = get_pending_github_login(
        session=session,
        provider=provider,
        provider_account_id=provider_account_id,
    )
    if existing is not None:
        existing.last_seen_at = now
        existing.attempt_count = (existing.attempt_count or 0) + 1
        if provider_login is not None:
            existing.provider_login = provider_login
        if email is not None:
            existing.email = email
        if full_name is not None:
            existing.full_name = full_name
        if avatar_url is not None:
            existing.avatar_url = avatar_url
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    db_obj = PendingGitHubLogin(
        provider=provider,
        provider_account_id=str(provider_account_id),
        provider_login=provider_login,
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
        first_seen_at=now,
        last_seen_at=now,
        attempt_count=1,
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def delete_pending_github_login(
    *, session: Session, pending: PendingGitHubLogin
) -> None:
    session.delete(pending)
    session.commit()


def create_user_from_github(
    *,
    session: Session,
    email: str,
    full_name: str | None = None,
) -> User:
    """Create a local user from a GitHub identity (no usable password).

    The hashed_password is set to a random argon2 hash so password login is
    effectively disabled until the admin sets one. ``is_active`` defaults to
    True; ``is_superuser`` is False.
    """
    random_password = secrets.token_urlsafe(48)
    db_obj = User(
        email=email,
        full_name=full_name,
        is_active=True,
        is_superuser=False,
        hashed_password=get_password_hash(random_password),
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj
