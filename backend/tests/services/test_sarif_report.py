"""Which of a repository's findings reach the security tab, and where from.

``test_sarif.py`` covers the format. This covers the query: the right
repository, the right engine, only findings the team still has, and a file path
a checkout on the runner can actually resolve.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import Session

from app.models import (
    DockerFinding,
    DockerTarget,
    Engine,
    RuleDomain,
    ScanStatus,
    Severity,
)
from app.models.db.docker import DockerScan
from app.services.sarif_report import (
    SARIF_SPECS,
    collect_findings,
    sarif_for_repository,
)
from tests.fixtures.factories import (
    make_finding,
    make_org,
    make_repo,
    make_rule,
    make_scan,
    make_workflow_file,
)

_NOW = datetime.now(timezone.utc)
_PATHS = iter(f".github/workflows/w{n}.yml" for n in range(1, 100))


def _workflow_finding(session: Session, repo, **kw):  # type: ignore[no-untyped-def]
    """One open CI finding on its own workflow file.

    A distinct path per call: workflow files are unique per
    ``(repo, branch, path)``, so a shared default would collide the moment a
    test wants two findings.
    """
    wf = kw.pop("workflow_file", None) or make_workflow_file(
        session, repo, path=next(_PATHS)
    )
    rule = kw.pop("rule", None) or make_rule(session)
    scan = make_scan(session, repo, wf)
    return make_finding(session, scan, rule, workflow_file=wf, **kw)


# ─── Scoping ─────────────────────────────────────────────────────────────────


def test_only_this_repositorys_findings_are_reported(db: Session) -> None:
    """The token proves one repository; nothing else may leak through it."""
    org = make_org(db)
    mine = make_repo(db, org)
    theirs = make_repo(db, org)
    _workflow_finding(db, mine, message="mine")
    _workflow_finding(db, theirs, message="theirs")

    findings = collect_findings(db, mine.id, SARIF_SPECS[Engine.workflow])

    assert [f.message for f in findings] == ["mine"]


def test_a_resolved_finding_is_not_reported(db: Session) -> None:
    """It is not something the repository still has."""
    org = make_org(db)
    repo = make_repo(db, org)
    _workflow_finding(db, repo, message="open")
    _workflow_finding(db, repo, message="gone", resolved_at=_NOW)

    findings = collect_findings(db, repo.id, SARIF_SPECS[Engine.workflow])

    assert [f.message for f in findings] == ["open"]


def test_an_ignored_finding_is_not_reported(db: Session) -> None:
    """The team already said not to raise it.

    Re-raising it in the security tab would leave the two views disagreeing
    about the same finding, and the dismissal made here would look ignored.
    """
    org = make_org(db)
    repo = make_repo(db, org)
    _workflow_finding(db, repo, message="open")
    _workflow_finding(db, repo, message="muted", ignored_at=_NOW)

    findings = collect_findings(db, repo.id, SARIF_SPECS[Engine.workflow])

    assert [f.message for f in findings] == ["open"]


# ─── What each finding carries ───────────────────────────────────────────────


def test_a_workflow_finding_takes_its_path_from_the_file_row(db: Session) -> None:
    """The CI engine persists its files, so the path is on the joined row
    rather than on the finding — the one place the four engines differ."""
    org = make_org(db)
    repo = make_repo(db, org)
    wf = make_workflow_file(db, repo, path=".github/workflows/release.yml")
    # The test database is not truncated between runs, so a fixed slug
    # collides with itself on the second invocation.
    slug = f"sarif-{uuid.uuid4().hex[:8]}"
    rule = make_rule(db, slug=slug, severity=Severity.critical)
    _workflow_finding(
        db,
        repo,
        workflow_file=wf,
        rule=rule,
        severity=Severity.critical,
        line_start=12,
        line_end=14,
        fingerprint="fp0001",
    )

    finding = collect_findings(db, repo.id, SARIF_SPECS[Engine.workflow])[0]

    assert finding.file_path == ".github/workflows/release.yml"
    assert finding.line_start == 12
    assert finding.line_end == 14
    assert finding.rule_slug == slug
    assert finding.severity == Severity.critical
    assert finding.fingerprint == "fp0001"


def test_a_leading_slash_is_stripped_from_the_path(db: Session) -> None:
    """SARIF URIs are repository-relative; a leading slash makes GitHub look
    for the file at the filesystem root of the runner and find nothing."""
    org = make_org(db)
    repo = make_repo(db, org)
    wf = make_workflow_file(db, repo, path="/.github/workflows/ci.yml")
    _workflow_finding(db, repo, workflow_file=wf)

    finding = collect_findings(db, repo.id, SARIF_SPECS[Engine.workflow])[0]

    assert finding.file_path == ".github/workflows/ci.yml"


def test_the_rules_title_and_description_come_from_the_catalog(db: Session) -> None:
    org = make_org(db)
    repo = make_repo(db, org)
    rule = make_rule(
        db,
        slug=f"sarif-{uuid.uuid4().hex[:8]}",
        title="Cache key never changes",
        description="A constant key serves a stale cache forever.",
    )
    _workflow_finding(db, repo, rule=rule)

    finding = collect_findings(db, repo.id, SARIF_SPECS[Engine.workflow])[0]

    assert finding.rule_title == "Cache key never changes"
    assert finding.rule_description == "A constant key serves a stale cache forever."


# ─── Another engine, same shape ──────────────────────────────────────────────


def test_a_docker_finding_carries_its_own_path(db: Session) -> None:
    """The other three engines store the path on the finding itself."""
    org = make_org(db)
    repo = make_repo(db, org)
    target = DockerTarget(repo_id=repo.id, root_path="services/api")
    db.add(target)
    db.commit()
    db.refresh(target)
    scan = DockerScan(docker_target_id=target.id, status=ScanStatus.completed)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    rule = make_rule(
        db,
        slug=f"sarif-{uuid.uuid4().hex[:8]}",
        domain=RuleDomain.container_docker,
    )
    db.add(
        DockerFinding(
            docker_target_id=target.id,
            scan_id=scan.id,
            rule_id=rule.id,
            severity=Severity.high,
            category=rule.category,
            message="Runs as root",
            file_path="services/api/Dockerfile",
            line_start=7,
            fingerprint="fp0002",
        )
    )
    db.commit()

    findings = collect_findings(db, repo.id, SARIF_SPECS[Engine.docker])

    assert len(findings) == 1
    assert findings[0].file_path == "services/api/Dockerfile"
    assert findings[0].line_start == 7


def test_one_engines_report_does_not_contain_anothers(db: Session) -> None:
    """A repository has findings from several engines; each workflow uploads
    its own, and GitHub keys alerts by the tool that reported them."""
    org = make_org(db)
    repo = make_repo(db, org)
    _workflow_finding(db, repo, message="a workflow problem")

    docker = collect_findings(db, repo.id, SARIF_SPECS[Engine.docker])

    assert docker == []


# ─── The whole document ──────────────────────────────────────────────────────


def test_the_report_names_the_engine_it_speaks_for(db: Session) -> None:
    """GitHub groups alerts by tool name, so two engines must not share one."""
    org = make_org(db)
    repo = make_repo(db, org)
    _workflow_finding(db, repo)

    document = sarif_for_repository(db, repo, Engine.workflow)

    driver = document["runs"][0]["tool"]["driver"]
    assert driver["name"].endswith("(workflow)")
    assert len(document["runs"][0]["results"]) == 1


def test_a_repository_with_nothing_open_still_gets_a_document(db: Session) -> None:
    org = make_org(db)
    repo = make_repo(db, org)

    document = sarif_for_repository(db, repo, Engine.workflow)

    assert document["runs"][0]["results"] == []
    assert document["version"] == "2.1.0"
