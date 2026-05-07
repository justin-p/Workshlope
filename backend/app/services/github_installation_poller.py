from __future__ import annotations

import logging
import threading

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import GithubAppInstallation, GithubInstallationRepository
from app.services.github_installation_polling import (
    GithubInstallationPollingError,
    fetch_app_installations,
    fetch_installation_repositories,
    github_app_installation_ids_from_api_rows,
)

logger = logging.getLogger(__name__)

_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()


def prune_github_installations_removed_on_github(
    *, session: Session, live_installation_ids: set[int]
) -> int:
    """Delete local rows for installations GitHub no longer lists (user uninstalled).

    ``LessonRepo.github_installation_id`` uses ON DELETE SET NULL.
    Entitlement rows cascade with the installation row.
    """
    stored = session.exec(select(GithubAppInstallation.id)).all()
    removed = 0
    for inst_id in stored:
        if inst_id in live_installation_ids:
            continue
        row = session.get(GithubAppInstallation, inst_id)
        if row is not None:
            session.delete(row)
            removed += 1
    return removed


def _sync_installations_once() -> None:
    installation_rows = fetch_app_installations(settings=settings)
    with Session(engine) as session:
        for row in installation_rows:
            install_id_raw = row.get("id")
            account = row.get("account")
            if not isinstance(install_id_raw, int) or not isinstance(account, dict):
                continue

            login = account.get("login")
            account_type = account.get("type")
            account_id = account.get("id")
            if (
                not isinstance(login, str)
                or not isinstance(account_type, str)
                or not isinstance(account_id, int)
            ):
                continue

            installation = session.get(GithubAppInstallation, install_id_raw)
            if installation is None:
                installation = GithubAppInstallation(
                    id=install_id_raw,
                    account_id=account_id,
                    account_login=login,
                    account_type=account_type,
                    target_type=str(row.get("target_type") or account_type),
                    repository_selection=(
                        str(row.get("repository_selection"))
                        if row.get("repository_selection")
                        else None
                    ),
                    app_slug=str(row.get("app_slug")) if row.get("app_slug") else None,
                )
            else:
                installation.account_id = account_id
                installation.account_login = login
                installation.account_type = account_type
                installation.target_type = str(
                    row.get("target_type") or installation.target_type
                )
                installation.repository_selection = (
                    str(row.get("repository_selection"))
                    if row.get("repository_selection")
                    else installation.repository_selection
                )
                installation.app_slug = (
                    str(row.get("app_slug"))
                    if row.get("app_slug")
                    else installation.app_slug
                )
            session.add(installation)

            if settings.GITHUB_INSTALLATION_POLL_REFRESH_REPOSITORIES:
                repo_names, selection_mode = fetch_installation_repositories(
                    settings=settings,
                    installation_id=installation.id,
                )
                if selection_mode:
                    installation.repository_selection = selection_mode
                session.add(installation)
                existing_rows = session.exec(
                    select(GithubInstallationRepository).where(
                        GithubInstallationRepository.installation_id == installation.id
                    )
                ).all()
                existing_map = {item.full_name: item for item in existing_rows}
                target = set(repo_names)
                for missing in sorted(target - set(existing_map.keys())):
                    session.add(
                        GithubInstallationRepository(
                            installation_id=installation.id,
                            full_name=missing,
                        )
                    )
                for stale_name in sorted(set(existing_map.keys()) - target):
                    session.delete(existing_map[stale_name])
        live_ids = github_app_installation_ids_from_api_rows(installation_rows)
        prune_github_installations_removed_on_github(
            session=session, live_installation_ids=live_ids
        )
        session.commit()


def _poll_loop() -> None:
    logger.info("github installation poller started")
    while not _STOP_EVENT.is_set():
        try:
            _sync_installations_once()
        except GithubInstallationPollingError:
            logger.exception("github installation poller refresh failed")
        except Exception:  # pragma: no cover
            logger.exception("unexpected github installation poller failure")

        wait_seconds = max(10, int(settings.GITHUB_INSTALLATION_POLL_INTERVAL_SECONDS))
        if _STOP_EVENT.wait(wait_seconds):
            break
    logger.info("github installation poller stopped")


def start_github_installation_poller() -> None:
    global _THREAD
    if not settings.GITHUB_INSTALLATION_POLL_ENABLED:
        return
    if _THREAD is not None and _THREAD.is_alive():
        return
    _STOP_EVENT.clear()
    _THREAD = threading.Thread(
        target=_poll_loop,
        name="github-installation-poller",
        daemon=True,
    )
    _THREAD.start()


def stop_github_installation_poller() -> None:
    global _THREAD
    if _THREAD is None:
        return
    _STOP_EVENT.set()
    _THREAD.join(
        timeout=max(3, int(settings.GITHUB_INSTALLATION_POLL_SHUTDOWN_TIMEOUT_SECONDS))
    )
    _THREAD = None
