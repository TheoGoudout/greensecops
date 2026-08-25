from fastapi import APIRouter

from app.api.routes import (
    badges,
    billing,
    cloud,
    docker,
    events,
    github_oauth,
    installations,
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
    workflow_findings,
    workflow_fixes,
    workflow_scans,
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
# The CI-workflow engine's three routers take their prefix here rather than in
# their own module, because each is mounted twice — see the aliases below.
_WORKFLOW_ROUTERS = (
    (workflow_scans, "/workflow-scans", "/analyses"),
    (workflow_findings, "/workflow-findings", "/issues"),
    (workflow_fixes, "/workflow-fixes", "/fixes"),
)
for _module, _prefix, _ in _WORKFLOW_ROUTERS:
    api_router.include_router(
        _module.router, prefix=_prefix, tags=[_prefix.lstrip("/")]
    )
api_router.include_router(rules.router)
api_router.include_router(webhooks.router)
api_router.include_router(badges.router)
api_router.include_router(telemetry.router)
api_router.include_router(billing.router)
api_router.include_router(terraform.router)
api_router.include_router(cloud.router)
api_router.include_router(docker.router)

# ─── Back-compatible aliases ─────────────────────────────────────────────────
#
# The CI-workflow engine's routes moved from /analyses, /issues and /fixes to
# /workflow-scans, /workflow-findings and /workflow-fixes, matching the tables
# and models they serve and the /terraform-roots, /docker-targets convention the
# other engines already follow.
#
# The old paths keep working for one release so a browser holding the previous
# frontend does not start 404-ing the moment the backend rolls out. They are
# `include_in_schema=False`, which keeps them out of OpenAPI and therefore out
# of the generated clients — nothing new is written against them, and deleting
# this block is the whole of the removal.
for _module, _, _legacy_prefix in _WORKFLOW_ROUTERS:
    # Tagged even though it never reaches OpenAPI: `custom_generate_unique_id`
    # in app/main.py reads `route.tags[0]`, and an untagged route raises there
    # before `include_in_schema` is ever consulted.
    api_router.include_router(
        _module.router,
        prefix=_legacy_prefix,
        tags=[f"{_legacy_prefix.lstrip('/')}-legacy"],
        include_in_schema=False,
    )

if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
