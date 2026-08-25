"""Tests for the /api/v1/docker-targets/ endpoints."""

import uuid
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Category,
    DockerBuildEnrichment,
    DockerBuildTelemetry,
    DockerFinding,
    DockerScan,
    DockerTarget,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    ScanTrigger,
    Severity,
    UserTier,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"dkapi-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
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
        full_name=f"dkapiowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=77777,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def target(db: Session, repo: Repository) -> DockerTarget:
    item = DockerTarget(repo_id=repo.id, root_path=f"svc/{uuid.uuid4().hex[:8]}")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def seeded_docker_rule(db: Session) -> Rule:
    rule = db.exec(
        select(Rule).where(Rule.domain == RuleDomain.container_docker)
    ).first()
    assert rule is not None
    return rule


@pytest.fixture()
def completed_scan(db: Session, target: DockerTarget) -> DockerScan:
    scan = DockerScan(
        docker_target_id=target.id,
        status=ScanStatus.completed,
        triggered_by=ScanTrigger.manual,
        score=72.0,
        grade="B",
        file_count=3,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


@dataclass
class FakeDockerFile:
    path: str
    content: str


# ─── POST /docker-targets/ ────────────────────────────────────────────────────


def test_create_docker_target(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/docker-targets/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "services/api"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["root_path"] == "services/api"
    assert body["enabled"] is True


@pytest.mark.parametrize("raw", ["", "/", "./", "  "])
def test_create_docker_target_normalizes_the_repository_root(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    raw: str,
) -> None:
    """All spellings of "the repo root" must collapse to one row.

    The unique constraint is on the literal string, so without normalization a
    repo could accumulate several root targets all scanning the same files.
    """
    response = client.post(
        f"{settings.API_V1_STR}/docker-targets/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": raw},
    )
    assert response.status_code == 201
    assert response.json()["root_path"] == ""


def test_create_docker_target_rejects_a_duplicate_path(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    target: DockerTarget,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/docker-targets/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": target.root_path},
    )
    assert response.status_code == 409


def test_create_docker_target_requires_auth(
    client: TestClient, repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/docker-targets/",
        json={"repo_id": str(repo.id), "root_path": "x"},
    )
    assert response.status_code == 401


# ─── GET /docker-targets/ ─────────────────────────────────────────────────────


def test_list_docker_targets_filtered_by_repo(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    target: DockerTarget,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [str(target.id)]


def test_list_docker_targets_surfaces_the_latest_grade(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    target: DockerTarget,
    completed_scan: DockerScan,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    body = response.json()[0]
    assert body["latest_grade"] == "B"
    assert body["latest_score"] == 72.0


def test_a_failed_scan_does_not_define_the_grade(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    target: DockerTarget,
    completed_scan: DockerScan,
) -> None:
    # A later failed scan must not erase the last good grade.
    db.add(
        DockerScan(
            docker_target_id=target.id,
            status=ScanStatus.failed,
            triggered_by=ScanTrigger.manual,
        )
    )
    db.commit()
    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    assert response.json()[0]["latest_grade"] == "B"


# ─── Tenant isolation ─────────────────────────────────────────────────────────


def test_another_tenants_target_is_404_not_403(
    client: TestClient,
    db: Session,
    target: DockerTarget,
) -> None:
    """Existence of another tenant's target must not be disclosed.

    A 403 would confirm the id is real; the route returns the same 404 detail
    for missing and unauthorized alike.
    """
    other_org = Organization(name=f"other-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(other_org)
    db.commit()
    db.refresh(other_org)
    email = f"outsider-{uuid.uuid4().hex[:8]}@example.com"
    from app import crud
    from app.models import UserCreate

    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password="password12345")
    )
    db.add(OrgMember(org_id=other_org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()

    login = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": "password12345"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/findings", headers=headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Docker target not found"


# ─── Scan trigger ─────────────────────────────────────────────────────────────


def test_trigger_scan_queues_the_task(
    client: TestClient, superuser_token_headers: dict[str, str], target: DockerTarget
) -> None:
    with patch("app.api.routes.docker.run_docker_scan.delay") as delay:
        response = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/scan",
            headers=superuser_token_headers,
        )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    delay.assert_called_once()


def test_trigger_scan_is_forbidden_on_a_disabled_target(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    target: DockerTarget,
) -> None:
    target.enabled = False
    db.add(target)
    db.commit()
    response = client.post(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/scan",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403


def test_toggle_flips_enabled(
    client: TestClient, superuser_token_headers: dict[str, str], target: DockerTarget
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/toggle",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_delete_removes_the_target(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    target: DockerTarget,
) -> None:
    target_id = target.id
    response = client.delete(
        f"{settings.API_V1_STR}/docker-targets/{target_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 204
    # The route deletes through its own session, so this one still holds the
    # row in its identity map. The id is captured above because expiring the
    # instance would make reading it re-select a row that no longer exists.
    db.expire_all()
    assert db.get(DockerTarget, target_id) is None


# ─── Findings ─────────────────────────────────────────────────────────────────


def _add_finding(
    db: Session,
    target: DockerTarget,
    scan: DockerScan,
    rule: Rule,
    **overrides: object,
) -> DockerFinding:
    values: dict[str, object] = {
        "scan_id": scan.id,
        "docker_target_id": target.id,
        "rule_id": rule.id,
        "file_path": "Dockerfile",
        "fingerprint": uuid.uuid4().hex[:16],
        "severity": Severity.high,
        "category": Category.security,
        "message": "runs as root",
    }
    values.update(overrides)
    finding = DockerFinding(**values)  # type: ignore[arg-type]
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


def test_list_findings_returns_the_rule_slug_and_locators(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    target: DockerTarget,
    completed_scan: DockerScan,
    seeded_docker_rule: Rule,
) -> None:
    _add_finding(
        db,
        target,
        completed_scan,
        seeded_docker_rule,
        service_name="api",
        line_start=4,
        line_end=9,
    )
    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()[0]
    assert body["rule_slug"] == seeded_docker_rule.slug
    assert body["service_name"] == "api"
    assert body["line_start"] == 4
    assert body["line_end"] == 9


def test_list_findings_hides_resolved_by_default(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    target: DockerTarget,
    completed_scan: DockerScan,
    seeded_docker_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    _add_finding(
        db,
        target,
        completed_scan,
        seeded_docker_rule,
        resolved_at=datetime.now(timezone.utc),
    )
    default = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/findings",
        headers=superuser_token_headers,
    )
    assert default.json() == []

    included = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/findings",
        headers=superuser_token_headers,
        params={"include_resolved": True},
    )
    assert len(included.json()) == 1


# ─── Scans ────────────────────────────────────────────────────────────────────


def test_list_scans_exposes_the_file_count(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    target: DockerTarget,
    completed_scan: DockerScan,
) -> None:
    # The score is a mean of per-file scores; without the denominator the
    # grade can't be reasoned about.
    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/scans",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()[0]["file_count"] == 3


# ─── Files ────────────────────────────────────────────────────────────────────


def test_list_files_classifies_each_file(
    client: TestClient, superuser_token_headers: dict[str, str], target: DockerTarget
) -> None:
    with patch(
        "app.api.routes.docker._fetch_docker_files",
        return_value=[
            FakeDockerFile(path="compose.yml", content="services: {}\n"),
            FakeDockerFile(path="Dockerfile", content="FROM x\n"),
        ],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/files",
            headers=superuser_token_headers,
        )
    assert response.status_code == 200
    body = response.json()
    # Sorted by path, and each carries the kind the viewer needs.
    assert [f["path"] for f in body] == ["Dockerfile", "compose.yml"]
    assert [f["kind"] for f in body] == ["dockerfile", "compose"]


def test_list_files_reports_a_github_failure_as_502(
    client: TestClient, superuser_token_headers: dict[str, str], target: DockerTarget
) -> None:
    with patch(
        "app.api.routes.docker._fetch_docker_files",
        side_effect=RuntimeError("upstream is down"),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/files",
            headers=superuser_token_headers,
        )
    assert response.status_code == 502


# ─── Badges ───────────────────────────────────────────────────────────────────


def test_public_target_badge_needs_no_signature(
    client: TestClient, target: DockerTarget, completed_scan: DockerScan
) -> None:
    response = client.get(f"{settings.API_V1_STR}/badges/docker/{target.id}.svg")
    assert response.status_code == 200
    assert "Docker" in response.text
    assert "B" in response.text


def test_private_target_badge_requires_a_valid_signature(
    client: TestClient,
    db: Session,
    repo: Repository,
    target: DockerTarget,
    completed_scan: DockerScan,
) -> None:
    repo.is_private = True
    db.add(repo)
    db.commit()

    unsigned = client.get(f"{settings.API_V1_STR}/badges/docker/{target.id}.json")
    assert unsigned.json()["message"] == "not configured"

    from app.services.badge_signing import sign_badge

    signed = client.get(
        f"{settings.API_V1_STR}/badges/docker/{target.id}.json",
        params={"sig": sign_badge(str(target.id))},
    )
    assert signed.json()["message"] == "B"


def test_unknown_target_badge_is_indistinguishable_from_unauthorized(
    client: TestClient,
) -> None:
    response = client.get(f"{settings.API_V1_STR}/badges/docker/{uuid.uuid4()}.json")
    assert response.json()["message"] == "not configured"


def test_superuser_sees_targets_across_orgs(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    target: DockerTarget,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/", headers=superuser_token_headers
    )
    assert response.status_code == 200
    assert str(target.id) in {t["id"] for t in response.json()}


def test_findings_for_a_missing_target_are_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{uuid.uuid4()}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 404


# ─── WorkflowFix generation and delivery ──────────────────────────────────────────────


def test_generate_fixes_groups_findings_by_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    target: DockerTarget,
    completed_scan: DockerScan,
    seeded_docker_rule: Rule,
) -> None:
    """One LLM call per file, not per finding.

    Two findings in one file and one in another must queue two generations,
    each carrying its file's whole finding set — cheaper than per-finding, and
    it stops two fixes racing to patch the same lines.
    """
    _add_finding(db, target, completed_scan, seeded_docker_rule, file_path="Dockerfile")
    _add_finding(db, target, completed_scan, seeded_docker_rule, file_path="Dockerfile")
    _add_finding(
        db, target, completed_scan, seeded_docker_rule, file_path="compose.yml"
    )

    with patch("app.api.routes.docker.run_docker_fix_generation.delay") as delay:
        response = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/fixes",
            headers=superuser_token_headers,
            json={},
        )
    assert response.status_code == 202
    assert response.json()["queued"] == 2
    assert delay.call_count == 2
    queued_sizes = sorted(len(c.kwargs["finding_ids"]) for c in delay.call_args_list)
    assert queued_sizes == [1, 2]


def test_generate_fixes_with_no_open_findings_queues_nothing(
    client: TestClient, superuser_token_headers: dict[str, str], target: DockerTarget
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/fixes",
        headers=superuser_token_headers,
        json={},
    )
    assert response.status_code == 202
    assert response.json() == {"status": "no_findings", "queued": 0}


def test_a_second_generation_request_does_not_duplicate_an_in_flight_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    target: DockerTarget,
    completed_scan: DockerScan,
    seeded_docker_rule: Rule,
) -> None:
    _add_finding(db, target, completed_scan, seeded_docker_rule, file_path="Dockerfile")

    with patch("app.api.routes.docker.run_docker_fix_generation.delay"):
        first = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/fixes",
            headers=superuser_token_headers,
            json={},
        )
        second = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/fixes",
            headers=superuser_token_headers,
            json={},
        )
    assert first.json()["queued"] == 1
    # The first request's fix is still pending, so the second must not reset it
    # out from under the worker.
    assert second.json()["queued"] == 0


def test_deliver_returns_the_deterministic_branch(
    client: TestClient, superuser_token_headers: dict[str, str], target: DockerTarget
) -> None:
    from app.services.delivery_pr import docker_fix_branch

    with patch("app.api.routes.docker.deliver_docker_fixes.delay") as delay:
        response = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/deliver",
            headers=superuser_token_headers,
        )
    assert response.status_code == 202
    assert response.json()["pr_branch"] == docker_fix_branch(target.id)
    delay.assert_called_once()


def test_list_fixes_is_scoped_to_the_target(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    target: DockerTarget,
) -> None:
    from app.models import DockerFix, LLMProvider
    from app.models.enums import FixStatus

    db.add(
        DockerFix(
            docker_target_id=target.id,
            file_path="Dockerfile",
            llm_provider=LLMProvider.openai,
            llm_model="gpt-4o-mini",
            status=FixStatus.ready,
            full_content="FROM python:3.12-slim\n",
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/fixes",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["file_path"] == "Dockerfile"
    assert body[0]["status"] == "ready"


# ─── GET /docker-targets/{id}/runtime ────────────────────────────────────────


@pytest.fixture()
def seeded_runtime_rule(db: Session) -> Rule:
    rule = db.exec(
        select(Rule).where(Rule.domain == RuleDomain.container_runtime)
    ).first()
    assert rule is not None
    return rule


def _make_telemetry(
    db: Session, repo: Repository, dockerfile_path: str | None, **kwargs: object
) -> DockerBuildTelemetry:
    row = DockerBuildTelemetry(
        repo_id=repo.id,
        workflow_run_id=int(uuid.uuid4().int % 10**9),
        dockerfile_path=dockerfile_path,
        **kwargs,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_list_runtime_returns_builds_with_their_findings(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    target: DockerTarget,
    seeded_runtime_rule: Rule,
) -> None:
    telemetry = _make_telemetry(
        db,
        repo,
        f"{target.root_path}/Dockerfile",
        image_size_bytes=2_400_000_000,
        containers='[{"name": "api", "peak_rss_bytes": 90000000}]',
    )
    db.add(
        DockerBuildEnrichment(
            repo_id=repo.id,
            telemetry_id=telemetry.id,
            rule_slug=seeded_runtime_rule.slug,
            evidence="container 'api' peaked at 90 MB",
            recommendation="Set a limit from the measured peak.",
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/runtime",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["image_size_bytes"] == 2_400_000_000
    # The JSON columns are decoded server-side so the tab never parses a string
    # out of a typed field.
    assert body[0]["containers"] == [{"name": "api", "peak_rss_bytes": 90000000}]
    assert len(body[0]["findings"]) == 1
    finding = body[0]["findings"][0]
    assert finding["rule_slug"] == seeded_runtime_rule.slug
    # Severity comes from the catalog, not from the stored enrichment.
    assert finding["severity"] == seeded_runtime_rule.severity.value
    assert finding["rule_title"] == seeded_runtime_rule.title


def test_list_runtime_excludes_builds_owned_by_another_target(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    target: DockerTarget,
) -> None:
    # A build under a *different* target's root must not appear here, or a
    # monorepo would count the same image twice.
    other = DockerTarget(repo_id=repo.id, root_path=f"other/{uuid.uuid4().hex[:8]}")
    db.add(other)
    db.commit()
    db.refresh(other)
    _make_telemetry(db, repo, f"{other.root_path}/Dockerfile")

    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{target.id}/runtime",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


def test_list_runtime_gives_unattributed_builds_to_the_repo_root(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    # A build reported without the action's dockerfile_path input names no
    # file; the repo-root target is the only one that can claim it.
    root = DockerTarget(repo_id=repo.id, root_path="")
    db.add(root)
    db.commit()
    db.refresh(root)
    _make_telemetry(db, repo, None)

    response = client.get(
        f"{settings.API_V1_STR}/docker-targets/{root.id}/runtime",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


# ─── POST /docker-targets/{id}/runtime-fixes ─────────────────────────────────


def _make_enrichment(
    db: Session, repo: Repository, telemetry_id: uuid.UUID, slug: str
) -> DockerBuildEnrichment:
    row = DockerBuildEnrichment(
        repo_id=repo.id,
        telemetry_id=telemetry_id,
        rule_slug=slug,
        evidence="container 'api' peaked at 420 MB with no memory limit set",
        recommendation="Set a memory limit around 630 MB.",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_runtime_fix_queues_generation_for_the_measured_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    target: DockerTarget,
    seeded_runtime_rule: Rule,
) -> None:
    from app.models import DockerFix

    file_path = f"{target.root_path}/Dockerfile"
    telemetry = _make_telemetry(db, repo, file_path)
    enrichment = _make_enrichment(db, repo, telemetry.id, seeded_runtime_rule.slug)

    with patch("app.api.routes.docker.run_docker_fix_generation.delay") as queued:
        response = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/runtime-fixes",
            headers=superuser_token_headers,
            json={"enrichment_ids": [str(enrichment.id)]},
        )

    assert response.status_code == 202
    assert response.json()["queued"] == 1
    queued.assert_called_once()
    kwargs = queued.call_args.kwargs
    assert kwargs["enrichment_ids"] == [str(enrichment.id)]
    # No static finding exists for this file, so the task needs the target and
    # path passed explicitly — there is no finding to read them off.
    assert kwargs["file_path"] == file_path
    assert kwargs["docker_target_id"] == str(target.id)

    fix = db.exec(
        select(DockerFix)
        .where(DockerFix.docker_target_id == target.id)
        .where(DockerFix.file_path == file_path)
    ).first()
    assert fix is not None


def test_runtime_fix_skips_builds_with_no_dockerfile_path(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    target: DockerTarget,
    seeded_runtime_rule: Rule,
) -> None:
    # Without the join back to source there is no file to rewrite, and guessing
    # one would push an edit to a file nobody measured.
    telemetry = _make_telemetry(db, repo, None)
    enrichment = _make_enrichment(db, repo, telemetry.id, seeded_runtime_rule.slug)

    with patch("app.api.routes.docker.run_docker_fix_generation.delay") as queued:
        response = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/runtime-fixes",
            headers=superuser_token_headers,
            json={"enrichment_ids": [str(enrichment.id)]},
        )

    assert response.status_code == 202
    assert response.json() == {"status": "no_dockerfile_path", "queued": 0}
    queued.assert_not_called()


def test_runtime_fix_folds_in_open_static_findings_for_the_same_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    target: DockerTarget,
    seeded_docker_rule: Rule,
    seeded_runtime_rule: Rule,
    completed_scan: DockerScan,
) -> None:
    # One rewrite per file, or a runtime fix and a static fix would race to
    # patch the same lines.
    file_path = f"{target.root_path}/Dockerfile"
    finding = DockerFinding(
        scan_id=completed_scan.id,
        docker_target_id=target.id,
        rule_id=seeded_docker_rule.id,
        file_path=file_path,
        fingerprint=uuid.uuid4().hex[:16],
        severity=Severity.high,
        category=Category.security,
        message="runs as root",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)

    telemetry = _make_telemetry(db, repo, file_path)
    enrichment = _make_enrichment(db, repo, telemetry.id, seeded_runtime_rule.slug)

    with patch("app.api.routes.docker.run_docker_fix_generation.delay") as queued:
        response = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/runtime-fixes",
            headers=superuser_token_headers,
            json={"enrichment_ids": [str(enrichment.id)]},
        )

    assert response.status_code == 202
    kwargs = queued.call_args.kwargs
    assert kwargs["finding_ids"] == [str(finding.id)]
    assert kwargs["enrichment_ids"] == [str(enrichment.id)]


def test_runtime_fix_rejects_enrichments_from_another_repo(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    org: Organization,
    repo: Repository,
    target: DockerTarget,
    seeded_runtime_rule: Rule,
) -> None:
    other_repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"dkapiowner/other-{uuid.uuid4().hex[:8]}",
        installation_id=77777,
    )
    db.add(other_repo)
    db.commit()
    db.refresh(other_repo)
    telemetry = _make_telemetry(db, other_repo, "Dockerfile")
    enrichment = _make_enrichment(
        db, other_repo, telemetry.id, seeded_runtime_rule.slug
    )

    with patch("app.api.routes.docker.run_docker_fix_generation.delay") as queued:
        response = client.post(
            f"{settings.API_V1_STR}/docker-targets/{target.id}/runtime-fixes",
            headers=superuser_token_headers,
            json={"enrichment_ids": [str(enrichment.id)]},
        )

    assert response.status_code == 202
    assert response.json()["queued"] == 0
    queued.assert_not_called()
