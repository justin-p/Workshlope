"""GitHub OAuth integration routes.

Two responsibilities:

1. ``/oauth/github/bridge`` - exchange a verified GitHub identity (signed by the
   external Auth.js service) for either an internal API JWT (already linked
   user) or a pending-approval response (first-time GitHub login that needs an
   admin to approve and link/create the user).
2. ``/oauth/github/pending/...`` and ``/oauth/github/users/{user_id}/...`` -
   admin-only management endpoints used by the Users page to review pending
   logins, approve/deny them, unlink GitHub accounts, and inspect link status.
"""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from jwt.exceptions import InvalidTokenError

from app import crud
from app.api.deps import SessionDep, get_current_active_superuser
from app.core import security
from app.core.config import settings
from app.models import (
    ApprovePendingRequest,
    BridgeResponse,
    GitHubBridgeRequest,
    Message,
    OAuthAccountPublic,
    PendingGitHubLoginPublic,
    PendingGitHubLoginsPublic,
    User,
)

router = APIRouter(prefix="/oauth/github", tags=["oauth"])

PROVIDER = "github"


def _issue_access_token(user_id: uuid.UUID) -> str:
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return security.create_access_token(user_id, expires_delta=expires)


@router.post("/bridge", response_model=BridgeResponse)
def bridge_login(*, session: SessionDep, body: GitHubBridgeRequest) -> Any:
    """Exchange a verified GitHub identity for an API JWT, or queue a pending request.

    - If the GitHub identity is already linked to an active user, returns
      ``status="signed_in"`` with an access token.
    - If the linked user is inactive, returns 403.
    - Otherwise, upserts a pending-approval record and returns
      ``status="pending_approval"`` with the pending row id.
    """
    try:
        identity = security.verify_bridge_token(body.bridge_token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bridge token",
        ) from exc

    if identity.get("provider") != PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported provider",
        )

    raw_provider_account_id = identity.get("provider_account_id")
    if not raw_provider_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bridge token missing provider_account_id",
        )
    provider_account_id = str(raw_provider_account_id)
    provider_login = identity.get("provider_login")
    email = identity.get("email")
    full_name = identity.get("name") or identity.get("full_name")
    avatar_url = identity.get("avatar_url") or identity.get("picture")

    account = crud.get_oauth_account(
        session=session,
        provider=PROVIDER,
        provider_account_id=provider_account_id,
    )

    if account is not None:
        user = session.get(User, account.user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not active",
            )
        crud.sync_linked_github_oauth_from_bridge_claims(
            session=session,
            account=account,
            provider_login=provider_login,
            avatar_url=avatar_url,
        )
        return BridgeResponse(
            status="signed_in",
            access_token=_issue_access_token(user.id),
            token_type="bearer",
        )

    pending = crud.upsert_pending_github_login(
        session=session,
        provider=PROVIDER,
        provider_account_id=provider_account_id,
        provider_login=provider_login,
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
    )
    return BridgeResponse(status="pending_approval", pending_id=pending.id)


@router.get(
    "/pending",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=PendingGitHubLoginsPublic,
)
def list_pending_logins(*, session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """Admin: list pending GitHub login requests (most recent first)."""
    rows, count = crud.list_pending_github_logins(
        session=session, skip=skip, limit=limit
    )
    return PendingGitHubLoginsPublic(
        data=[PendingGitHubLoginPublic.model_validate(r) for r in rows], count=count
    )


@router.post(
    "/pending/{pending_id}/approve",
    response_model=OAuthAccountPublic,
)
def approve_pending_login(
    *,
    session: SessionDep,
    pending_id: uuid.UUID,
    body: ApprovePendingRequest,
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    """Admin: approve a pending GitHub login.

    The body must include exactly one of ``user_id`` (link to an existing user)
    or ``create_user=true`` (create a new user from the pending profile and
    link to it).
    """
    pending = crud.get_pending_github_login_by_id(
        session=session, pending_id=pending_id
    )
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pending request not found"
        )

    has_user_id = body.user_id is not None
    if has_user_id == body.create_user:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one of user_id or create_user=true",
        )

    if (
        crud.get_oauth_account(
            session=session,
            provider=pending.provider,
            provider_account_id=pending.provider_account_id,
        )
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GitHub account already linked to a user",
        )

    if has_user_id:
        assert body.user_id is not None
        user = session.get(User, body.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        if (
            crud.get_oauth_account_for_user(
                session=session, user_id=user.id, provider=pending.provider
            )
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already has a GitHub account linked",
            )
    else:
        if not pending.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pending request has no email; cannot create a new user",
            )
        if crud.get_user_by_email(session=session, email=pending.email) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            )
        user = crud.create_user_from_github(
            session=session,
            email=pending.email,
            full_name=pending.full_name,
        )

    account = crud.create_oauth_account(
        session=session,
        user_id=user.id,
        provider=pending.provider,
        provider_account_id=pending.provider_account_id,
        provider_login=pending.provider_login,
        avatar_url=pending.avatar_url,
        linked_by_user_id=current_user.id,
    )
    crud.delete_pending_github_login(session=session, pending=pending)
    return account


@router.delete(
    "/pending/{pending_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=Message,
)
def deny_pending_login(*, session: SessionDep, pending_id: uuid.UUID) -> Message:
    """Admin: deny a pending request by deleting it."""
    pending = crud.get_pending_github_login_by_id(
        session=session, pending_id=pending_id
    )
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pending request not found"
        )
    crud.delete_pending_github_login(session=session, pending=pending)
    return Message(message="Pending request denied")


@router.get(
    "/users/{user_id}/status",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=OAuthAccountPublic | None,
)
def get_link_status(*, session: SessionDep, user_id: uuid.UUID) -> Any:
    """Return the GitHub link for a user, or ``null`` if none."""
    return crud.get_oauth_account_for_user(
        session=session, user_id=user_id, provider=PROVIDER
    )


@router.delete(
    "/users/{user_id}/link",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=Message,
)
def admin_unlink_github(*, session: SessionDep, user_id: uuid.UUID) -> Message:
    deleted = crud.delete_oauth_account_for_user(
        session=session, user_id=user_id, provider=PROVIDER
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="No GitHub link to remove")
    return Message(message="GitHub link removed")
