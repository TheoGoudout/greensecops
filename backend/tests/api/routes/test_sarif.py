"""GET /{engine}/sarif — the endpoint a Code Scanning workflow calls.

The authorization story is the whole point of these: the caller is a workflow
run rather than a person, and the only thing it may ask for is its own
repository's findings, because the repository comes from the signed OIDC claim
and not from anything the caller chose.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import verify_github_oidc_token
from app.core.config import settings
from app.main import app
from app.models import DockerTarget, Organization, Repository, UserTier
from tests.fixtures.factories import (
    make_finding,
    make_rule,
    make_scan,
    make_workflow_file,
)

ENGINES = ("workflow", "terraform", "docker", "ansible")


def _claims(repo_full_name: str) -> dict:
    return {
        "repository": repo_full_name,
        "repository_owner": repo_full_name.split("/")[0],
        "workflow": "Code scanning",
        "ref": "refs/heads/main",
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "greensecops",
    }


@pytest.fixture()
def as_repo(db: Session):  # type: ignore[no-untyped-def]
    """A registered repository, and a token that proves the caller is it."""
    org = Organization(name=f"sarif-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"acme/sarif-{uuid.uuid4().hex[:8]}",
        installation_id=4242,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)

    app.dependency_overrides[verify_github_oidc_token] = lambda: _claims(
        repository.full_name
    )
    yield repository
    app.dependency_overrides.pop(verify_github_oidc_token, None)


def _get(client: TestClient, engine: str) -> dict:
    response = client.get(f"{settings.API_V1_STR}/{engine}/sarif")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


# ─── Every engine answers ────────────────────────────────────────────────────


@pytest.mark.parametrize("engine", ENGINES)
def test_each_file_engine_serves_a_sarif_log(
    client: TestClient, as_repo: Repository, engine: str
) -> None:
    """A repository with nothing registered for an engine still gets a valid
    empty log — that is what closes whatever alerts the last run raised."""
    document = _get(client, engine)

    assert document["version"] == "2.1.0"
    assert document["runs"][0]["results"] == []
    assert document["runs"][0]["tool"]["driver"]["name"].endswith(f"({engine})")


def test_the_report_contains_the_repositorys_open_findings(
    client: TestClient, db: Session, as_repo: Repository
) -> None:
    wf = make_workflow_file(db, as_repo, path=".github/workflows/ci.yml")
    rule = make_rule(db, slug=f"sarif-route-{uuid.uuid4().hex[:8]}")
    scan = make_scan(db, as_repo, wf)
    make_finding(db, scan, rule, workflow_file=wf, message="Action is not pinned")

    document = _get(client, "workflow")

    results = document["runs"][0]["results"]
    assert [r["message"]["text"] for r in results] == ["Action is not pinned"]
    location = results[0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == ".github/workflows/ci.yml"


# ─── Authorization ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("engine", ENGINES)
def test_without_a_token_there_is_no_report(client: TestClient, engine: str) -> None:
    """The findings are the customer's; an unauthenticated caller gets none."""
    response = client.get(f"{settings.API_V1_STR}/{engine}/sarif")

    assert response.status_code == 401


def test_an_unregistered_repository_is_told_so(client: TestClient, db: Session) -> None:
    """A real workflow with a valid token, on a repo nobody added.

    The message has to say what to do, because the only person who will ever
    read it is looking at a red step in their own CI log.
    """
    app.dependency_overrides[verify_github_oidc_token] = lambda: _claims(
        "acme/never-registered"
    )
    try:
        response = client.get(f"{settings.API_V1_STR}/workflow/sarif")
    finally:
        app.dependency_overrides.pop(verify_github_oidc_token, None)

    assert response.status_code == 404
    assert "acme/never-registered" in response.json()["detail"]
    assert "dashboard" in response.json()["detail"]


def test_a_token_cannot_reach_another_repositorys_findings(
    client: TestClient, db: Session, as_repo: Repository
) -> None:
    """There is no id in the path, so there is nothing to tamper with — this
    pins that the route really does read the claim and not a parameter."""
    other = Repository(
        org_id=as_repo.org_id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"acme/other-{uuid.uuid4().hex[:8]}",
        installation_id=4243,
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    wf = make_workflow_file(db, other, path=".github/workflows/theirs.yml")
    rule = make_rule(db, slug=f"sarif-other-{uuid.uuid4().hex[:8]}")
    scan = make_scan(db, other, wf)
    make_finding(db, scan, rule, workflow_file=wf, message="not yours")

    document = _get(client, "workflow")

    assert document["runs"][0]["results"] == []


# ─── POST /{engine}/scans — the other half of the flow ───────────────────────


@pytest.mark.parametrize("engine", ENGINES)
def test_a_scan_cannot_be_triggered_without_a_token(
    client: TestClient, engine: str
) -> None:
    response = client.post(f"{settings.API_V1_STR}/{engine}/scans")

    assert response.status_code == 401


def test_triggering_a_workflow_scan_queues_the_repository(
    client: TestClient, as_repo: Repository
) -> None:
    """Repo-level, not a fan-out: the CI worker discovers the files itself, so
    a list built from our rows would scan a stale set."""
    with patch("app.api.routes.workflow_scans.run_static_analysis.delay") as delay:
        response = client.post(f"{settings.API_V1_STR}/workflow/scans")

    assert response.status_code == 202
    assert delay.call_args.kwargs["repo_id"] == str(as_repo.id)
    # Named for what asked, not "manual" — nobody clicked anything.
    assert delay.call_args.kwargs["trigger"] == "code_scanning"


def test_triggering_a_docker_scan_fans_out_over_enabled_targets(
    client: TestClient, db: Session, as_repo: Repository
) -> None:
    enabled = DockerTarget(repo_id=as_repo.id, root_path="services/api", enabled=True)
    disabled = DockerTarget(repo_id=as_repo.id, root_path="legacy", enabled=False)
    db.add(enabled)
    db.add(disabled)
    db.commit()
    db.refresh(enabled)

    with patch("app.api.routes.docker.run_docker_scan.delay") as delay:
        response = client.post(f"{settings.API_V1_STR}/docker/scans")

    assert response.status_code == 202
    assert response.json()["queued"] == "1"
    # The disabled target stays disabled: the switch means "do not spend
    # analyses on this", and an OIDC call is not a reason to override it.
    assert delay.call_count == 1
    assert delay.call_args.kwargs["docker_target_id"] == str(enabled.id)


def test_a_repository_with_no_targets_queues_nothing(
    client: TestClient, as_repo: Repository
) -> None:
    """Answering 202 with a count of zero rather than erroring: the workflow
    is copied from an example and a repo with no Terraform is not a failure."""
    with patch("app.api.routes.terraform.run_terraform_scan.delay") as delay:
        response = client.post(f"{settings.API_V1_STR}/terraform/scans")

    assert response.status_code == 202
    assert response.json() == {"status": "no_targets", "queued": "0"}
    delay.assert_not_called()


def test_a_scan_cannot_be_triggered_for_an_unregistered_repository(
    client: TestClient,
) -> None:
    app.dependency_overrides[verify_github_oidc_token] = lambda: _claims(
        "acme/never-registered"
    )
    try:
        with patch("app.api.routes.docker.run_docker_scan.delay") as delay:
            response = client.post(f"{settings.API_V1_STR}/docker/scans")
    finally:
        app.dependency_overrides.pop(verify_github_oidc_token, None)

    assert response.status_code == 404
    delay.assert_not_called()
