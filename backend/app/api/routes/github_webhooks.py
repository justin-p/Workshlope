from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import GithubAppInstallation, GithubWebhookDelivery, get_datetime_utc

router = APIRouter(prefix="/github", tags=["github-integration"])

_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def reset_github_webhook_rate_limiter_for_tests() -> None:
    """Clear in-process webhook rate buckets (tests only)."""
    with _RATE_LOCK:
        _RATE_BUCKETS.clear()


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


def _enforce_github_webhook_rate_limit(client_host: str | None) -> None:
    """Sliding-window limit per client IP for signed webhook abuse."""
    limit = int(settings.GITHUB_WEBHOOK_MAX_REQUESTS_PER_MINUTE_PER_IP)
    window = float(settings.GITHUB_WEBHOOK_RATE_LIMIT_WINDOW_SECONDS)
    if limit <= 0:
        return
    key = client_host or "unknown"
    now = time.time()
    with _RATE_LOCK:
        bucket = _RATE_BUCKETS[key]
        while bucket and bucket[0] < now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Webhook rate limit exceeded",
            )
        bucket.append(now)


def _reserve_delivery_idempotent(
    *, session: Session, delivery_id: str, github_event: str
) -> bool:
    """Return True if this is a replay (delivery already processed)."""
    trimmed = delivery_id[:128]
    session.add(
        GithubWebhookDelivery(
            delivery_id=trimmed,
            github_event=github_event[:128],
            received_at=get_datetime_utc(),
        ),
    )
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return True
    return False


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
    client_host = request.client.host if request.client else None
    _enforce_github_webhook_rate_limit(client_host)

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

    github_event = request.headers.get("x-github-event", "")
    delivery_id = (request.headers.get("x-github-delivery") or "").strip()

    try:
        payload: dict[str, Any] = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed payload",
        ) from exc

    if delivery_id and _reserve_delivery_idempotent(
        session=session,
        delivery_id=delivery_id,
        github_event=github_event,
    ):
        return {"ok": True, "idempotent": True}

    if github_event == "ping":
        session.commit()
        return {"ok": True}

    if github_event != "installation":
        session.commit()
        return {"ignored": github_event}

    action = payload.get("action")
    installation = payload.get("installation") or {}

    inst_id_raw = installation.get("id")
    if inst_id_raw is None:
        session.commit()
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

    session.commit()
    return {"ok": True, "unknown_action": action}
