"""Every engine refuses a colliding action the same way.

The rule lives in ``services/state_machines/engine_target.py``; these tests are
about the wiring — that each engine's scan, fix and delivery routes actually
consult it, and that they all say the same thing when they refuse.

Written as one module across five engines on purpose. Split per engine, the
thing most worth checking — that the wording and the status code do *not* drift
apart the way the button labels did — would be five separate assertions nobody
compares.
"""

import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import (
    AnsibleFix,
    AnsibleProject,
    AnsibleScan,
    CloudAccount,
    CloudScan,
    DockerFix,
    DockerScan,
    DockerTarget,
    FixStatus,
    LLMProvider,
    Organization,
    Repository,
    ScanStatus,
    ScanTrigger,
    TerraformFix,
    TerraformRoot,
    TerraformScan,
    UserTier,
    WorkflowScan,
)
from tests.fixtures.factories import make_fix, make_org, make_repo, make_workflow_file

# ─── Shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    return make_org(db, tier=UserTier.free)


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    return make_repo(db, org)


@pytest.fixture(autouse=True)
def _no_workers() -> Iterator[None]:
    """Every route under test ends in a ``.delay()``. The guard has to fire
    before that, so a test that reaches one has already failed — but patching
    them keeps a regression from queueing real Celery work."""
    targets = [
        "app.api.routes.terraform.run_terraform_scan.delay",
        "app.api.routes.terraform.deliver_terraform_fixes.delay",
        "app.api.routes.docker.run_docker_scan.delay",
        "app.api.routes.docker.deliver_docker_fixes.delay",
        "app.api.routes.ansible.run_ansible_scan.delay",
        "app.api.routes.ansible.deliver_ansible_fixes.delay",
        "app.api.routes.cloud.run_cloud_scan.delay",
        "app.workers.tasks.static_analysis.run_static_analysis.delay",
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay",
    ]
    patches = [patch(t) for t in targets]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


def _url(path: str) -> str:
    return f"{settings.API_V1_STR}{path}"


def _assert_conflict(response: Any, reason: str, target_label: str) -> None:
    """One shape of refusal, checked identically for every engine."""
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert reason in detail, detail
    assert f"for this {target_label}" in detail, detail


# ─── The three file engines ──────────────────────────────────────────────────
#
# Parameterised over the engines that share ``EngineSpec``, since the only thing
# that differs between them is the noun in the URL and in the message.

_FILE_ENGINES = [
    pytest.param("terraform", id="terraform"),
    pytest.param("docker", id="docker"),
    pytest.param("ansible", id="ansible"),
]

_ENGINE_SHAPE: dict[str, dict[str, Any]] = {
    "terraform": {
        "target_model": TerraformRoot,
        "scan_model": TerraformScan,
        "fix_model": TerraformFix,
        "fk": "terraform_root_id",
        "collection": "terraform/roots",
        "label": "Terraform root",
    },
    "docker": {
        "target_model": DockerTarget,
        "scan_model": DockerScan,
        "fix_model": DockerFix,
        "fk": "docker_target_id",
        "collection": "docker/targets",
        "label": "Docker target",
    },
    "ansible": {
        "target_model": AnsibleProject,
        "scan_model": AnsibleScan,
        "fix_model": AnsibleFix,
        "fk": "ansible_project_id",
        "collection": "ansible/projects",
        "label": "Ansible project",
    },
}


def _make_target(db: Session, engine: str, repo: Repository) -> Any:
    shape = _ENGINE_SHAPE[engine]
    target = shape["target_model"](
        repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}"
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def _make_scan(db: Session, engine: str, target: Any, status: ScanStatus) -> Any:
    shape = _ENGINE_SHAPE[engine]
    scan = shape["scan_model"](
        **{shape["fk"]: target.id},
        repo_id=target.repo_id,
        status=status,
        triggered_by=ScanTrigger.manual,
    )
    db.add(scan)
    db.commit()
    return scan


def _make_engine_fix(db: Session, engine: str, target: Any, status: FixStatus) -> Any:
    shape = _ENGINE_SHAPE[engine]
    fix = shape["fix_model"](
        **{shape["fk"]: target.id},
        file_path="main.tf",
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=status,
    )
    db.add(fix)
    db.commit()
    return fix


@pytest.mark.parametrize("engine", _FILE_ENGINES)
@pytest.mark.parametrize("action", ["scans", "fixes", "deliveries"])
def test_running_scan_blocks_every_action(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    engine: str,
    action: str,
) -> None:
    """The rule the whole change exists for: while an analysis is running,
    nothing else may start against the same target."""
    shape = _ENGINE_SHAPE[engine]
    target = _make_target(db, engine, repo)
    _make_scan(db, engine, target, ScanStatus.running)

    response = client.post(
        _url(f"/{shape['collection']}/{target.id}/{action}"),
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "a scan is already running", shape["label"])


@pytest.mark.parametrize("engine", _FILE_ENGINES)
def test_queued_scan_blocks_a_second_scan(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    engine: str,
) -> None:
    """``queued`` counts as busy too — the duplicate used to return 202 and then
    be dropped by the worker's Redis lock with nothing said."""
    shape = _ENGINE_SHAPE[engine]
    target = _make_target(db, engine, repo)
    _make_scan(db, engine, target, ScanStatus.queued)

    response = client.post(
        _url(f"/{shape['collection']}/{target.id}/scans"),
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "a scan is already running", shape["label"])


@pytest.mark.parametrize("engine", _FILE_ENGINES)
@pytest.mark.parametrize("fix_status", [FixStatus.pending, FixStatus.generating])
def test_generating_fix_blocks_scan_and_delivery_but_not_generation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    engine: str,
    fix_status: FixStatus,
) -> None:
    shape = _ENGINE_SHAPE[engine]
    target = _make_target(db, engine, repo)
    _make_engine_fix(db, engine, target, fix_status)

    for action in ("scans", "deliveries"):
        _assert_conflict(
            client.post(
                _url(f"/{shape['collection']}/{target.id}/{action}"),
                headers=superuser_token_headers,
            ),
            "fixes are being generated",
            shape["label"],
        )

    # Generating a second file's fix is ordinary work, so it is let through —
    # there are simply no findings to act on here.
    allowed = client.post(
        _url(f"/{shape['collection']}/{target.id}/fixes"),
        headers=superuser_token_headers,
    )
    assert allowed.status_code == 202, allowed.text


@pytest.mark.parametrize("engine", _FILE_ENGINES)
@pytest.mark.parametrize("action", ["scans", "fixes", "deliveries"])
def test_delivering_fix_blocks_every_action(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    engine: str,
    action: str,
) -> None:
    shape = _ENGINE_SHAPE[engine]
    target = _make_target(db, engine, repo)
    _make_engine_fix(db, engine, target, FixStatus.delivering)

    response = client.post(
        _url(f"/{shape['collection']}/{target.id}/{action}"),
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "a pull request is being opened", shape["label"])


@pytest.mark.parametrize("engine", _FILE_ENGINES)
@pytest.mark.parametrize(
    "scan_status", [ScanStatus.completed, ScanStatus.failed, ScanStatus.no_targets]
)
def test_a_finished_scan_blocks_nothing(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    engine: str,
    scan_status: ScanStatus,
) -> None:
    """A failed scan is a finished one. Treating it as activity would leave a
    target permanently unscannable after one bad run."""
    shape = _ENGINE_SHAPE[engine]
    target = _make_target(db, engine, repo)
    _make_scan(db, engine, target, scan_status)

    response = client.post(
        _url(f"/{shape['collection']}/{target.id}/scans"),
        headers=superuser_token_headers,
    )

    assert response.status_code == 202, response.text


@pytest.mark.parametrize("engine", _FILE_ENGINES)
def test_only_the_latest_scan_counts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    engine: str,
) -> None:
    """A registered target's activity follows the same "most recent scan" rule
    the card's own status badge shows, so the tooltip and the badge cannot
    disagree — an older running row swept long ago must not block forever."""
    shape = _ENGINE_SHAPE[engine]
    target = _make_target(db, engine, repo)
    _make_scan(db, engine, target, ScanStatus.running)
    _make_scan(db, engine, target, ScanStatus.completed)

    response = client.post(
        _url(f"/{shape['collection']}/{target.id}/scans"),
        headers=superuser_token_headers,
    )

    assert response.status_code == 202, response.text


def test_docker_runtime_fixes_share_the_guard(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    """Docker's second fix route is a fix route like any other."""
    target = _make_target(db, "docker", repo)
    _make_scan(db, "docker", target, ScanStatus.running)

    response = client.post(
        _url(f"/docker/targets/{target.id}/runtime-fixes"),
        headers=superuser_token_headers,
        json={"enrichment_ids": [str(uuid.uuid4())]},
    )

    _assert_conflict(response, "a scan is already running", "Docker target")


# ─── Cloud ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def cloud_account(db: Session, org: Organization) -> CloudAccount:
    account = CloudAccount(
        org_id=org.id,
        display_name=f"acct-{uuid.uuid4().hex[:8]}",
        role_arn="arn:aws:iam::123456789012:role/greensecops",
        external_id=uuid.uuid4().hex,
        regions="us-east-1",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_cloud_scan_blocked_while_scanning(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    cloud_account: CloudAccount,
) -> None:
    db.add(
        CloudScan(
            cloud_account_id=cloud_account.id,
            status=ScanStatus.running,
            triggered_by=ScanTrigger.manual,
        )
    )
    db.commit()

    response = client.post(
        _url(f"/cloud/accounts/{cloud_account.id}/scans"),
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "a scan is already running", "cloud account")


def test_cloud_scan_allowed_when_idle(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    cloud_account: CloudAccount,
) -> None:
    response = client.post(
        _url(f"/cloud/accounts/{cloud_account.id}/scans"),
        headers=superuser_token_headers,
    )
    assert response.status_code == 202, response.text


# ─── CI workflow ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/workflow/repositories/{repo}/scans",
        "/workflow/repositories/{repo}/fixes",
        "/workflow/repositories/{repo}/fixes/regenerate",
        "/workflow/repositories/{repo}/deliveries",
    ],
)
def test_repo_scoped_workflow_routes_blocked_while_scanning(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    path: str,
) -> None:
    db.add(
        WorkflowScan(
            repo_id=repo.id,
            content_hash=uuid.uuid4().hex,
            status=ScanStatus.running,
            triggered_by=ScanTrigger.manual,
        )
    )
    db.commit()

    response = client.post(
        _url(path.format(repo=repo.id)), headers=superuser_token_headers
    )

    _assert_conflict(response, "a scan is already running", "repository")


def test_workflow_repo_scan_counts_any_unfinished_row_not_just_the_latest(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    """A CI analysis writes one scan row per workflow file under a single
    repo-wide lock, so "the most recent row" would happily be a finished one
    while a sibling was still running."""
    db.add(
        WorkflowScan(
            repo_id=repo.id,
            content_hash=uuid.uuid4().hex,
            status=ScanStatus.running,
            triggered_by=ScanTrigger.manual,
        )
    )
    db.commit()
    db.add(
        WorkflowScan(
            repo_id=repo.id,
            content_hash=uuid.uuid4().hex,
            status=ScanStatus.completed,
            triggered_by=ScanTrigger.manual,
        )
    )
    db.commit()

    response = client.post(
        _url(f"/workflow/repositories/{repo.id}/scans"),
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "a scan is already running", "repository")


def test_repo_wide_delivery_blocked_while_a_fix_generates(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    """A repo-wide PR opened mid-generation would be missing the fixes still
    being written into it."""
    wf_file = make_workflow_file(db, repo, path=".github/workflows/guard.yml")
    make_fix(db, wf_file, status=FixStatus.generating)

    response = client.post(
        _url(f"/workflow/repositories/{repo.id}/deliveries"),
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "fixes are being generated", "repository")


def test_file_scoped_delivery_ignores_another_files_generation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    """The escape hatch from the rule above: one file's ready fix can still be
    shipped while another file's is being written."""
    busy_file = make_workflow_file(db, repo, path=".github/workflows/busy.yml")
    make_fix(db, busy_file, status=FixStatus.generating)
    ready_file = make_workflow_file(db, repo, path=".github/workflows/ready.yml")
    ready = make_fix(
        db, ready_file, status=FixStatus.ready, full_content="on: push\njobs: {}\n"
    )

    response = client.post(
        _url(f"/workflow/fixes/{ready.id}/deliveries"),
        headers=superuser_token_headers,
    )

    assert response.status_code == 202, response.text


def test_file_scoped_scan_blocked_by_a_repo_wide_analysis(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    """``static_analysis`` takes one lock per repository, so a repo-wide run
    holds every file in it."""
    wf_file = make_workflow_file(db, repo, path=".github/workflows/one.yml")
    db.add(
        WorkflowScan(
            repo_id=repo.id,
            content_hash=uuid.uuid4().hex,
            status=ScanStatus.running,
            triggered_by=ScanTrigger.manual,
        )
    )
    db.commit()

    response = client.post(
        _url(f"/workflow/files/{wf_file.id}/scans"),
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "a scan is already running", "workflow file")


def test_forced_delivery_does_not_bypass_the_guard(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
) -> None:
    """``force`` overrides the fix's own status — "deliver this even though it
    isn't ready" — not a collision with work a worker is doing right now."""
    wf_file = make_workflow_file(db, repo, path=".github/workflows/forced.yml")
    fix = make_fix(db, wf_file, status=FixStatus.delivering)

    response = client.post(
        _url(f"/workflow/fixes/{fix.id}/deliveries"),
        params={"force": "true"},
        headers=superuser_token_headers,
    )

    _assert_conflict(response, "a pull request is being opened", "workflow file")
