"""Role-declaring router.

Every endpoint in this API must state who may call it, in its own decorator::

    @router.get("/{repo_id}", role=Role.org_member, response_model=RepositoryPublic)

That is the whole point of :class:`RoleRouter`: ``role`` is keyword-only with no
default, so an endpoint that forgets it fails at import rather than shipping
silently unguarded. Before this existed, authorization was spread across three
conventions — a ``dependencies=[Depends(get_current_active_superuser)]`` on some
routes, an inline ``if`` in the body of others, and nothing at all on the rest —
and a reviewer had to read the body to find out which.

The declared role is enforced *before* the endpoint body runs, as a FastAPI
dependency, so no work happens on behalf of a caller who may not ask for it.

Roles are also where per-route rate limits are attached (``limit=``), keeping one
decorator per endpoint instead of stacking a second one underneath.
"""

import enum
import re
import uuid
from collections.abc import Callable
from typing import Any, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Request, params
from fastapi.types import DecoratedCallable
from sqlmodel import Session

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
    get_current_user,
)
from app.core.config import settings
from app.core.rate_limit import NO_RATE_LIMIT, rate_limit_dependency
from app.models import (
    AnsibleFinding,
    AnsibleProject,
    CloudAccount,
    CloudFinding,
    DockerFinding,
    DockerTarget,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    TerraformFinding,
    TerraformRoot,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
)


class Role(str, enum.Enum):
    """Who may call an endpoint.

    Two independent axes are flattened into one enum because an endpoint only
    ever needs one of them: a *global* axis (``guest`` → ``user`` → ``admin``)
    and a *tenant* axis (``org_member`` → ``org_admin`` → ``org_owner``) that
    grades a user's ``OrgRole`` within the organization owning the addressed
    resource.

    ``service`` and ``user_sse`` inject no dependency of their own — those
    endpoints authenticate in ways a shared dependency cannot express (HMAC over
    the raw body, GitHub's RS256 OIDC tokens, a single-use SSE ticket). They are
    declarations, not enforcement, and they still buy the two things every other
    role buys: a reader can see the intent without opening the body, and the
    route gets its own rate-limit class.
    """

    guest = "guest"
    """No authentication at all — public badges, health, the login endpoints."""

    service = "service"
    """A machine, not a person: HMAC-signed webhooks and GitHub OIDC ingest."""

    user_sse = "user_sse"
    """An authenticated user arriving over the SSE ticket-or-header flow."""

    user = "user"
    """Any active authenticated user; the endpoint scopes its own results."""

    org_member = "org_member"
    """Member of the organization owning the resource named in the path."""

    org_admin = "org_admin"
    """Admin or owner of that organization."""

    org_owner = "org_owner"
    """Owner of that organization."""

    admin = "admin"
    """Platform superuser (``User.is_superuser``)."""


# Org roles are hierarchical: an owner may do anything an admin may, and an
# admin anything a member may. Superusers satisfy every role (see _check_org_role).
_REQUIRED_RANK: dict[Role, int] = {
    Role.org_member: 0,
    Role.org_admin: 1,
    Role.org_owner: 2,
}

_HELD_RANK: dict[OrgRole, int] = {
    OrgRole.member: 0,
    OrgRole.admin: 1,
    OrgRole.owner: 2,
}


# ─── Resolving the organization that owns the addressed resource ──────────────
#
# An org role is meaningless without knowing *which* org, and the only thing a
# generic dependency can see is the request's path parameters. Each resolver
# walks that id back to an org_id; every chain below is a foreign key declared
# in models/db/. Returning None means "no such resource", which the caller turns
# into the same 404 a non-member gets, so a probe cannot distinguish the two.


def _org_of_repo(session: Session, repo_id: uuid.UUID) -> uuid.UUID | None:
    repo = session.get(Repository, repo_id)
    return repo.org_id if repo else None


def _org_of_workflow_file(
    session: Session, workflow_file_id: uuid.UUID
) -> uuid.UUID | None:
    workflow_file = session.get(WorkflowFile, workflow_file_id)
    return _org_of_repo(session, workflow_file.repo_id) if workflow_file else None


def _org_of_workflow_scan(session: Session, scan_id: uuid.UUID) -> uuid.UUID | None:
    scan = session.get(WorkflowScan, scan_id)
    return _org_of_repo(session, scan.repo_id) if scan else None


def _org_of_fix(session: Session, fix_id: uuid.UUID) -> uuid.UUID | None:
    fix = session.get(WorkflowFix, fix_id)
    return _org_of_workflow_file(session, fix.workflow_file_id) if fix else None


def _org_of_workflow_finding(
    session: Session, finding_id: uuid.UUID
) -> uuid.UUID | None:
    finding = session.get(WorkflowFinding, finding_id)
    # ``analysis_id`` is the column name the table still carries; the public
    # schema and the path parameter both call it ``scan_id``.
    return _org_of_workflow_scan(session, finding.analysis_id) if finding else None


def _org_of_cloud_account(session: Session, account_id: uuid.UUID) -> uuid.UUID | None:
    account = session.get(CloudAccount, account_id)
    return account.org_id if account else None


def _org_of_docker_target(session: Session, target_id: uuid.UUID) -> uuid.UUID | None:
    target = session.get(DockerTarget, target_id)
    return _org_of_repo(session, target.repo_id) if target else None


def _org_of_ansible_project(
    session: Session, project_id: uuid.UUID
) -> uuid.UUID | None:
    project = session.get(AnsibleProject, project_id)
    return _org_of_repo(session, project.repo_id) if project else None


def _org_of_terraform_root(session: Session, root_id: uuid.UUID) -> uuid.UUID | None:
    root = session.get(TerraformRoot, root_id)
    return _org_of_repo(session, root.repo_id) if root else None


# "finding_id" is already claimed by Workflow above — a bare "finding_id" here
# would resolve a Terraform/Docker/Ansible/Cloud finding's uuid against the
# WorkflowFinding table, since this dict is keyed by parameter name alone.
# Each engine's own finding routes must use one of these prefixed names.
def _org_of_terraform_finding(
    session: Session, terraform_finding_id: uuid.UUID
) -> uuid.UUID | None:
    finding = session.get(TerraformFinding, terraform_finding_id)
    return (
        _org_of_terraform_root(session, finding.terraform_root_id) if finding else None
    )


def _org_of_docker_finding(
    session: Session, docker_finding_id: uuid.UUID
) -> uuid.UUID | None:
    finding = session.get(DockerFinding, docker_finding_id)
    return _org_of_docker_target(session, finding.docker_target_id) if finding else None


def _org_of_ansible_finding(
    session: Session, ansible_finding_id: uuid.UUID
) -> uuid.UUID | None:
    finding = session.get(AnsibleFinding, ansible_finding_id)
    return (
        _org_of_ansible_project(session, finding.ansible_project_id)
        if finding
        else None
    )


def _org_of_cloud_finding(
    session: Session, cloud_finding_id: uuid.UUID
) -> uuid.UUID | None:
    finding = session.get(CloudFinding, cloud_finding_id)
    return _org_of_cloud_account(session, finding.cloud_account_id) if finding else None


def _org_of_organization(session: Session, org_id: uuid.UUID) -> uuid.UUID | None:
    return org_id if session.get(Organization, org_id) else None


class OrgResolver(NamedTuple):
    """How to reach an organization from one path parameter, and what to call it.

    ``detail`` matches the message the route bodies already used for the same
    resource, so centralising the check here does not degrade the error a client
    sees — and, since it is also the message a non-member gets, it keeps the
    missing and forbidden cases indistinguishable.
    """

    resolve: Callable[[Session, uuid.UUID], uuid.UUID | None]
    detail: str


ORG_RESOLVERS: dict[str, OrgResolver] = {
    "org_id": OrgResolver(_org_of_organization, "Organization not found"),
    "repo_id": OrgResolver(_org_of_repo, "Repository not found"),
    "workflow_file_id": OrgResolver(_org_of_workflow_file, "Workflow file not found"),
    "scan_id": OrgResolver(_org_of_workflow_scan, "Workflow scan not found"),
    "fix_id": OrgResolver(_org_of_fix, "Workflow fix not found"),
    "finding_id": OrgResolver(_org_of_workflow_finding, "Workflow finding not found"),
    "account_id": OrgResolver(_org_of_cloud_account, "Cloud account not found"),
    "target_id": OrgResolver(_org_of_docker_target, "Docker target not found"),
    "root_id": OrgResolver(_org_of_terraform_root, "Terraform root not found"),
    # A distinct name is mandatory, not stylistic: this dict is keyed by path
    # parameter, so an engine reusing "target_id" or "root_id" would have its
    # role checks resolved against another engine's table.
    "project_id": OrgResolver(_org_of_ansible_project, "Ansible project not found"),
    "terraform_finding_id": OrgResolver(
        _org_of_terraform_finding, "Terraform finding not found"
    ),
    "docker_finding_id": OrgResolver(
        _org_of_docker_finding, "Docker finding not found"
    ),
    "ansible_finding_id": OrgResolver(
        _org_of_ansible_finding, "Ansible finding not found"
    ),
    "cloud_finding_id": OrgResolver(_org_of_cloud_finding, "Cloud finding not found"),
}

_PATH_PARAM_RE = re.compile(r"\{([^}:]+)")

# Registry of every endpoint declared through a RoleRouter, keyed the way
# slowapi keys routes. tests/api/test_roles.py walks app.routes against this to
# catch anyone who reaches for a plain APIRouter and skips the role entirely.
ROUTE_ROLES: dict[str, Role] = {}


def _org_param(path: str) -> str | None:
    """Return the path parameter an org role would be resolved from, if any."""
    names: list[str] = _PATH_PARAM_RE.findall(path)
    for name in names:
        if name in ORG_RESOLVERS:
            return name
    return None


def _check_org_role(role: Role, param: str) -> Callable[..., None]:
    """Build the dependency enforcing an org-level ``role``.

    ``param`` is the path parameter the organization is resolved from, decided
    once at decoration time rather than re-derived per request.
    """
    required = _REQUIRED_RANK[role]
    resolver = ORG_RESOLVERS[param]
    not_found = HTTPException(status_code=404, detail=resolver.detail)

    def check(
        request: Request,
        session: SessionDep,
        current_user: CurrentUser,
    ) -> None:
        if current_user.is_superuser:
            return

        raw = request.path_params[param]
        try:
            resource_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
        except ValueError:
            raise not_found

        org_id = resolver.resolve(session, resource_id)
        if org_id is None:
            raise not_found

        membership = session.get(OrgMember, (org_id, current_user.id))
        if membership is None:
            # Same 404 a missing resource gets: authorize_repo/authorize_org in
            # deps.py deliberately hide tenant existence from non-members, and
            # answering 403 here would leak exactly what they hide.
            raise not_found

        if _HELD_RANK[membership.role] < required:
            # The caller is a member, so the resource's existence is not a
            # secret from them — an honest 403 is safe and more useful.
            raise HTTPException(
                status_code=403, detail="The user doesn't have enough privileges"
            )

    return check


def _role_dependencies(role: Role, path: str) -> list[params.Depends]:
    """Map a declared role onto the dependencies that enforce it.

    Raises at import when an org role has nothing to resolve an org from.
    Collection endpoints (``GET /repositories``, ``GET /workflow/findings``) address no
    single resource, so they cannot carry an org role — they take ``Role.user``
    and scope their own query with ``deps.user_org_ids``. Catching that here
    turns a would-be runtime 500 into an import failure the test suite trips on.
    """
    if role is Role.user:
        return [Depends(get_current_user)]
    if role is Role.admin:
        return [Depends(get_current_active_superuser)]
    if role in _REQUIRED_RANK:
        param = _org_param(path)
        if param is None:
            raise RuntimeError(
                f"Route {path!r} declares {role.value!r} but has no path parameter "
                f"an organization can be resolved from. Known parameters: "
                f"{', '.join(sorted(ORG_RESOLVERS))}."
            )
        return [Depends(_check_org_role(role, param))]
    # guest / service / user_sse authenticate (or don't) in the endpoint itself.
    return []


class RoleRouter(APIRouter):
    """An ``APIRouter`` whose route decorators require a ``role``.

    ``role`` is keyword-only and has no default, so omitting it is a ``TypeError``
    at import time and a mypy error before that. Everything else is passed
    through to ``APIRouter`` untouched, including a caller-supplied
    ``dependencies=`` list, which is merged rather than replaced.

    Each override below carries ``type: ignore[override]``: adding a required
    argument narrows the base signature and so violates Liskov substitution.
    That is the entire feature — a ``RoleRouter`` deliberately cannot be used
    wherever a bare ``APIRouter`` can, because the bare one lets you forget.
    """

    def get(  # type: ignore[override] # ty: ignore[invalid-method-override]
        self, path: str, *, role: Role, limit: str | None = None, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self._role_route(super().get, path, role, limit, **kwargs)

    def post(  # type: ignore[override] # ty: ignore[invalid-method-override]
        self, path: str, *, role: Role, limit: str | None = None, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self._role_route(super().post, path, role, limit, **kwargs)

    def put(  # type: ignore[override] # ty: ignore[invalid-method-override]
        self, path: str, *, role: Role, limit: str | None = None, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self._role_route(super().put, path, role, limit, **kwargs)

    def patch(  # type: ignore[override] # ty: ignore[invalid-method-override]
        self, path: str, *, role: Role, limit: str | None = None, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self._role_route(super().patch, path, role, limit, **kwargs)

    def delete(  # type: ignore[override] # ty: ignore[invalid-method-override]
        self, path: str, *, role: Role, limit: str | None = None, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self._role_route(super().delete, path, role, limit, **kwargs)

    def _role_route(
        self,
        factory: Callable[..., Callable[[DecoratedCallable], DecoratedCallable]],
        path: str,
        role: Role,
        limit: str | None,
        **kwargs: Any,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        role_dependencies = _role_dependencies(role, path)
        caller_dependencies = list(kwargs.pop("dependencies", None) or [])

        def register(func: DecoratedCallable) -> DecoratedCallable:
            # Keyed the way slowapi keys its counters, so ROUTE_ROLES and the
            # limiter agree on what identifies an endpoint and tests can line
            # this registry up against app.routes without a second convention.
            module = getattr(func, "__module__", "")
            name = getattr(func, "__name__", "")
            ROUTE_ROLES[f"{module}.{name}"] = role

            dependencies = []
            if limit != NO_RATE_LIMIT:
                # First in the list on purpose: a caller who is over their limit
                # should be turned away before the role check spends database
                # queries resolving their organization.
                dependencies.append(
                    Depends(
                        rate_limit_dependency(
                            limit or settings.RATE_LIMIT_DEFAULT, func
                        )
                    )
                )
            dependencies.extend(caller_dependencies)
            dependencies.extend(role_dependencies)

            return factory(path, dependencies=dependencies, **kwargs)(func)

        return register
