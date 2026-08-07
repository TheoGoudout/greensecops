from fastapi import APIRouter

from app.api.routes import (
    analyses,
    badges,
    billing,
    cloud,
    docker,
    events,
    fixes,
    github_oauth,
    installations,
    issues,
    login,
    organizations,
    overview,
    private,
    repositories,
    rules,
    telemetry,
    terraform,
    users,
    utils,
    webhooks,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(github_oauth.router)
api_router.include_router(installations.router)
api_router.include_router(organizations.router)
api_router.include_router(repositories.router)
api_router.include_router(overview.router)
api_router.include_router(events.router)
api_router.include_router(analyses.router)
api_router.include_router(issues.router)
api_router.include_router(fixes.router)
api_router.include_router(rules.router)
api_router.include_router(webhooks.router)
api_router.include_router(badges.router)
api_router.include_router(telemetry.router)
api_router.include_router(billing.router)
api_router.include_router(terraform.router)
api_router.include_router(cloud.router)
api_router.include_router(docker.router)

if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
