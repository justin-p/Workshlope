from fastapi import APIRouter

from app.api.routes import (
    github_webhooks,
    items,
    login,
    oauth,
    private,
    users,
    utils,
    workshop_badges,
    workshop_lessons,
    workshop_sessions,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(github_webhooks.router)
api_router.include_router(oauth.router)
api_router.include_router(workshop_sessions.router)
api_router.include_router(workshop_lessons.router)
api_router.include_router(workshop_badges.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
