"""Coverage for the mandatory per-endpoint role declaration.

Two things are being defended here. First, that *every* route declares a role —
the point of RoleRouter is that forgetting is impossible, and a plain APIRouter
slipping back into a route module would quietly undo that. Second, that the org
role hierarchy actually grades access, since OrgRole was persisted but never
enforced before this existed.
"""

import uuid

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_current_user
from app.api.router import (
    ORG_RESOLVERS,
    ROUTE_ROLES,
    Role,
    RoleRouter,
    _org_param,
    _role_dependencies,
)
from app.core.config import settings
from app.main import app
from app.models import (
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    TerraformRoot,
    User,
    UserTier,
)
from tests.utils.user import create_random_user, user_authentication_headers
from tests.utils.utils import random_lower_string


def _api_routes() -> list[APIRoute]:
    """Every APIRoute on the app, flattened.

    FastAPI 0.141 wraps each included router in a lazy ``_IncludedRouter``
    rather than splicing its routes into ``app.routes``, so a flat scan finds
    nothing and would make this whole module a silent no-op.
    """

    def walk(router: object) -> list[APIRoute]:
        found: list[APIRoute] = []
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                found.append(route)
            elif hasattr(route, "original_router"):
                found.extend(walk(route.original_router))
        return found

    return walk(app.router)


def test_every_route_declares_a_role() -> None:
    routes = _api_routes()
    assert routes, "route walk found nothing — the traversal is broken, not the app"

    undeclared = [
        f"{sorted(r.methods or [])} {r.path}"
        for r in routes
        if f"{r.endpoint.__module__}.{r.endpoint.__name__}" not in ROUTE_ROLES
    ]
    assert undeclared == [], (
        "these routes were registered without a role — they were probably added "
        "with a plain APIRouter instead of RoleRouter"
    )


def test_role_maps_to_an_enforcing_dependency() -> None:
    assert len(_role_dependencies(Role.user, "/")) == 1
    assert len(_role_dependencies(Role.admin, "/")) == 1
    assert len(_role_dependencies(Role.org_member, "/{repo_id}")) == 1
    # guest / service / user_sse authenticate inside the endpoint (or not at all).
    assert _role_dependencies(Role.guest, "/") == []
    assert _role_dependencies(Role.service, "/") == []
    assert _role_dependencies(Role.user_sse, "/") == []


def test_org_role_without_a_resolvable_resource_fails_at_decoration() -> None:
    router = RoleRouter()
    with pytest.raises(RuntimeError, match="no path parameter"):

        @router.get("/summary", role=Role.org_admin)
        def _unresolvable() -> None: ...  # pragma: no cover - never registered


def test_role_argument_is_mandatory() -> None:
    router = RoleRouter()
    with pytest.raises(TypeError):
        router.get("/whatever")  # type: ignore[call-arg]


def test_org_param_prefers_a_known_resolver() -> None:
    assert _org_param("/{repo_id}/branches") == "repo_id"
    assert _org_param("/oss-applications/{application_id}") is None
    assert set(ORG_RESOLVERS) >= {
        "org_id",
        "repo_id",
        "fix_id",
        "finding_id",
        "scan_id",
    }


# ─── Org role hierarchy, end to end ───────────────────────────────────────────


class _Member:
    def __init__(self, user: User, headers: dict[str, str]) -> None:
        self.user = user
        self.headers = headers


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"roles-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"rolesowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=int(uuid.uuid4().int % 10**8),
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def _member_with_role(
    client: TestClient, db: Session, org: Organization, role: OrgRole
) -> _Member:
    password = random_lower_string()
    user = create_random_user(db)
    from app import crud
    from app.models import UserUpdate

    user = crud.update_user(
        session=db, db_user=user, user_in=UserUpdate(password=password)
    )
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=role))
    db.commit()
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )
    return _Member(user, headers)


@pytest.fixture()
def outsider(client: TestClient, db: Session) -> _Member:
    """An authenticated user belonging to no organization at all."""
    password = random_lower_string()
    user = create_random_user(db)
    from app import crud
    from app.models import UserUpdate

    user = crud.update_user(
        session=db, db_user=user, user_in=UserUpdate(password=password)
    )
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )
    return _Member(user, headers)


def _toggle(client: TestClient, repo: Repository, headers: dict[str, str]):
    """PATCH /repositories/{repo_id} — declared role=Role.org_admin."""
    return client.patch(
        f"{settings.API_V1_STR}/repositories/{repo.id}",
        json={"enabled": True},
        headers=headers,
    )


def _read(client: TestClient, repo: Repository, headers: dict[str, str]):
    """GET /repositories/{repo_id} — declared role=Role.org_member."""
    return client.get(f"{settings.API_V1_STR}/repositories/{repo.id}", headers=headers)


@pytest.mark.parametrize(
    "org_role,expected",
    [(OrgRole.member, 403), (OrgRole.admin, 200), (OrgRole.owner, 200)],
)
def test_org_admin_route_grades_by_rank(
    client: TestClient,
    db: Session,
    org: Organization,
    repo: Repository,
    org_role: OrgRole,
    expected: int,
) -> None:
    member = _member_with_role(client, db, org, org_role)
    assert _toggle(client, repo, member.headers).status_code == expected


def test_org_member_route_accepts_the_lowest_rank(
    client: TestClient, db: Session, org: Organization, repo: Repository
) -> None:
    member = _member_with_role(client, db, org, OrgRole.member)
    assert _read(client, repo, member.headers).status_code == 200


def test_member_denied_an_admin_route_gets_403_not_404(
    client: TestClient, db: Session, org: Organization, repo: Repository
) -> None:
    """Existence is not a secret from someone already inside the org."""
    member = _member_with_role(client, db, org, OrgRole.member)
    response = _toggle(client, repo, member.headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "The user doesn't have enough privileges"


def test_non_member_gets_404_not_403(
    client: TestClient, repo: Repository, outsider: _Member
) -> None:
    """A non-member must not be able to tell the repository apart from a missing one."""
    denied = _toggle(client, repo, outsider.headers)
    missing = _toggle(
        client,
        Repository(
            id=uuid.uuid4(), org_id=uuid.uuid4(), github_repo_id=1, full_name="x/y"
        ),
        outsider.headers,
    )
    assert denied.status_code == missing.status_code == 404
    assert denied.json()["detail"] == missing.json()["detail"] == "Repository not found"


def test_superuser_satisfies_every_org_role(
    client: TestClient, repo: Repository, superuser_token_headers: dict[str, str]
) -> None:
    assert _toggle(client, repo, superuser_token_headers).status_code == 200


def test_unauthenticated_caller_is_rejected(
    client: TestClient, repo: Repository
) -> None:
    assert _toggle(client, repo, {}).status_code == 401


def test_role_router_merges_caller_supplied_dependencies() -> None:
    """A route's own dependencies= must survive alongside the role's."""
    from fastapi import Depends

    def _marker() -> None: ...  # pragma: no cover - never invoked

    router = RoleRouter()

    @router.get("/thing", role=Role.user, dependencies=[Depends(_marker)])
    def _endpoint() -> None: ...  # pragma: no cover - never invoked

    route = router.routes[0]
    assert isinstance(route, APIRoute)
    deps = [d.dependency for d in route.dependencies]

    assert _marker in deps, "a route's own dependencies must not be dropped"
    assert len(deps) == 3, "rate limit + the caller's + the role's"
    # The rate limit goes first so an over-budget caller is turned away before
    # the role check spends queries on them.
    assert deps[0].__name__ == "_endpoint"  # the limiter borrows the endpoint's name
    assert deps[-1] is get_current_user


@pytest.mark.parametrize("param", sorted(ORG_RESOLVERS))
def test_every_resolver_treats_an_unknown_id_as_no_org(db: Session, param: str) -> None:
    """A resolver must answer None rather than raise for an id that isn't there.

    None is what makes the dependency return the resource's ordinary 404, which
    is also what a non-member gets — the two have to stay indistinguishable.
    """
    assert ORG_RESOLVERS[param].resolve(db, uuid.uuid4()) is None


def test_resolver_walks_a_multi_hop_chain(
    db: Session, org: Organization, repo: Repository
) -> None:
    """root_id reaches an org only via TerraformRoot -> Repository -> org."""
    root = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(root)
    db.commit()
    db.refresh(root)

    assert ORG_RESOLVERS["root_id"].resolve(db, root.id) == org.id


def test_malformed_resource_id_is_a_404_not_a_500(
    client: TestClient, outsider: _Member
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/repositories/not-a-uuid/toggle",
        json={"enabled": True},
        headers=outsider.headers,
    )
    assert response.status_code in (404, 422)


def test_put_routes_also_require_a_role() -> None:
    """``PUT /workflow/findings/{finding_id}/ignore`` is the only PUT today;
    the override still has to behave for any other."""
    router = RoleRouter()

    @router.put("/thing", role=Role.admin)
    def _put_endpoint() -> None: ...  # pragma: no cover - never invoked

    assert f"{_put_endpoint.__module__}._put_endpoint" in ROUTE_ROLES
    with pytest.raises(TypeError):
        router.put("/other")  # type: ignore[call-arg]


def test_plain_apirouter_is_not_a_role_router() -> None:
    """Guard the guard: the registry check above only means something because a
    bare APIRouter genuinely accepts a route with no role."""
    router = APIRouter()

    @router.get("/unguarded")
    def _unguarded_endpoint() -> None: ...  # pragma: no cover - never invoked

    assert len(router.routes) == 1
    key = f"{_unguarded_endpoint.__module__}._unguarded_endpoint"
    assert key not in ROUTE_ROLES


# ─── Literal segments must out-rank the {id} patterns beside them ─────────────


@pytest.mark.parametrize(
    "path",
    [
        "/workflow/findings/stats",
        "/repositories/external",
        "/organizations/ai-providers",
        "/billing/plans",
    ],
)
def test_literal_segment_wins_over_a_sibling_id_pattern(
    client: TestClient, superuser_token_headers: dict[str, str], path: str
) -> None:
    """Each of these sits beside a ``/{some_id}`` route on the same prefix.

    FastAPI matches in declaration order, so a literal declared *after* its
    sibling pattern is swallowed by it and answers 422 "not a valid UUID" —
    which reads like a client bug rather than a routing one. Nothing else
    guards the ordering, and re-homing routes is exactly what disturbs it.
    """
    response = client.get(
        f"{settings.API_V1_STR}{path}", headers=superuser_token_headers
    )
    assert response.status_code != 422, (
        f"{path} was parsed as an id — its literal route is declared after the "
        "sibling {id} route and is unreachable"
    )
