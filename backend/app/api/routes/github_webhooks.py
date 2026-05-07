from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import Session

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import GithubAppInstallation, get_datetime_utc

router = APIRouter(prefix="/github", tags=["github-integration"])


def verify_github_signature_sha256(
    *, body: bytes, secret: str | None, signature_header: str | None
) -> bool:
    if secret is None or signature_header is None:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header.removeprefix("sha256=")
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hex, digest)


def _upsert_installation_from_payload(
    *,
    session: Session,
    installation: dict[str, Any],
) -> None:
    inst_id = int(installation["id"])
    account = installation.get("account") or {}
    raw_app = installation.get("app")
    app_payload: dict[str, Any] = {}
    if isinstance(raw_app, dict):
        app_payload = raw_app  # narrowed for mypy / ty
    app_slug_direct = installation.get("app_slug")
    login = account.get("login")
    row = session.get(GithubAppInstallation, inst_id)
    now = get_datetime_utc()

    if row is None:
        session.add(
            GithubAppInstallation(
                id=inst_id,
                account_id=int(account.get("id", 0)),
                account_login=str(login or ""),
                account_type=str(account.get("type") or ""),
                target_type=str(installation.get("target_type") or ""),
                repository_selection=str(installation.get("repository_selection") or "")
                or None,
                app_slug=str(app_payload.get("slug") or app_slug_direct or "") or None,
                suspended_at=None,
                created_at=now,
                updated_at=now,
            ),
        )
        return

    row.account_id = int(account.get("id", row.account_id))
    row.account_login = str(login or row.account_login)
    row.account_type = str(account.get("type") or row.account_type)
    row.target_type = str(installation.get("target_type") or row.target_type)
    repo_sel = installation.get("repository_selection")
    row.repository_selection = str(repo_sel) if repo_sel else None
    slug = app_payload.get("slug") or app_slug_direct
    row.app_slug = str(slug) if slug else None
    row.updated_at = now
    session.add(row)


@router.post("/webhooks")
async def github_webhook(request: Request, session: SessionDep) -> dict[str, Any]:
    """GitHub App webhook entrypoint (installation lifecycle MVP)."""
    if settings.GITHUB_WEBHOOK_SECRET is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub webhooks are not configured",
        )

    raw = await request.body()
    sig_header = request.headers.get("x-hub-signature-256")

    if not verify_github_signature_sha256(
        body=raw,
        secret=settings.GITHUB_WEBHOOK_SECRET,
        signature_header=sig_header,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"ok": True}

    if event != "installation":
        return {"ignored": event}

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed payload",
        ) from exc

    action = payload.get("action")
    installation = payload.get("installation") or {}

    inst_id_raw = installation.get("id")
    if inst_id_raw is None:
        return {"ok": True}

    inst_id = int(inst_id_raw)

    if action == "deleted":
        row = session.get(GithubAppInstallation, inst_id)
        if row is not None:
            session.delete(row)
        session.commit()
        return {"ok": True}

    if action == "suspend":
        row = session.get(GithubAppInstallation, inst_id)
        if row is not None:
            row.suspended_at = get_datetime_utc()
            row.updated_at = row.suspended_at
            session.add(row)
        session.commit()
        return {"ok": True, "action": action}

    if action == "unsuspend":
        row = session.get(GithubAppInstallation, inst_id)
        if row is not None:
            row.suspended_at = None
            row.updated_at = get_datetime_utc()
            session.add(row)
        session.commit()
        return {"ok": True, "action": action}

    if action in {"created", "new_permissions_accepted"}:
        _upsert_installation_from_payload(session=session, installation=installation)
        session.commit()
        return {"ok": True, "action": action}

    return {"ok": True, "unknown_action": action}
