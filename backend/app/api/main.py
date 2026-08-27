from fastapi import APIRouter

from app.api.routes import (
    ansible,
    auth,
    badges,
    billing,
    cloud,
    docker,
    events,
    installations,
    organizations,
    overview,
    private,
    repositories,
    rules,
    system,
    telemetry,
    terraform,
    users,
    webhooks,
    workflow_findings,
    workflow_fixes,
    workflow_scans,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(system.router)
api_router.include_router(installations.router)
api_router.include_router(organizations.router)
api_router.include_router(repositories.router)
api_router.include_router(overview.router)
api_router.include_router(rules.router)
# The CI-workflow engine's three routers share one prefix and one tag, so the
# engine reads as one resource from outside — `WorkflowService.listScans()`
# alongside `TerraformService.listScans()` — rather than as the three
# separately-tagged services the split modules would otherwise produce. The
# modules stay split because they are large, not because the API is.
for _module in (workflow_scans, workflow_findings, workflow_fixes):
    api_router.include_router(_module.router, prefix="/workflow", tags=["workflow"])
api_router.include_router(docker.router)
api_router.include_router(terraform.router)
api_router.include_router(cloud.router)
api_router.include_router(ansible.router)
api_router.include_router(badges.router)
api_router.include_router(telemetry.router)
api_router.include_router(billing.router)
api_router.include_router(webhooks.router)
# Stripe's handler lives in routes/billing.py with the rest of billing; it is
# mounted here so both providers answer under /webhooks with the same tag.
api_router.include_router(billing.webhook_router, prefix="/webhooks")
api_router.include_router(events.router)

if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
