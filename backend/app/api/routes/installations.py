import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from app import crud
from app.api.deps import CurrentUser, GitHubAppClientDep, SessionDep
from app.api.routes.webhooks import _enqueue_installation_sync
from app.models import Organization, OrganizationPublic, OrgMember

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/installations", tags=["installations"])


class InstallationSyncRequest(BaseModel):
    code: str
    redirect_uri: str | None = None


@router.get("/", response_model=list[OrganizationPublic])
def list_installations(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[OrganizationPublic]:
    """List all GitHub App installations linked to the current user."""
    orgs = session.exec(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)  # type: ignore[arg-type]
        .where(OrgMember.user_id == current_user.id)
    ).all()
    return [
        OrganizationPublic.model_validate(org, from_attributes=True) for org in orgs
    ]


@router.post("/sync", response_model=list[OrganizationPublic])
async def sync_installations(
    body: InstallationSyncRequest,
    session: SessionDep,
    current_user: CurrentUser,
    github_client: GitHubAppClientDep,
) -> list[OrganizationPublic]:
    """Verify, discover, and link every installation the user controls.

    Exchanges the OAuth ``code`` (issued during app installation when user
    authorization is enabled) for a user access token, then asks GitHub for the
    authoritative list of installations this user controls. Each is linked to the
    current user as an org owner and queued for repository sync. Idempotent —
    re-running doubles as a "refresh my installations" action.
    """
    try:
        user_token = await github_client.exchange_oauth_code(body.code, redirect_uri=body.redirect_uri)
        installations = await github_client.list_user_installations(user_token)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"GitHub installation sync failed: {exc}"
        ) from exc

    orgs: list[OrganizationPublic] = []
    for inst in installations:
        org = crud.upsert_organization(
            session=session,
            github_org_id=inst.account_id,
            name=inst.account_login,
            installation_id=inst.installation_id,
        )
        crud.add_org_owner(session=session, org_id=org.id, user_id=current_user.id)
        _enqueue_installation_sync(inst.installation_id, str(org.id))
        orgs.append(OrganizationPublic.model_validate(org, from_attributes=True))

    logger.info("Linked %d installation(s) for user %s", len(orgs), current_user.id)
    return orgs
