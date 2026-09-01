"""Per-engine repository grades: an average, per engine, from the latest scans.

The bug these pin: only the CI number was ever computed, so the Docker page
fell back to the *worst* of its targets' grades and the Infrastructure page
showed none at all.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.models import (
    DockerScan,
    DockerTarget,
    Engine,
    Repository,
    ScanStatus,
    ScanTrigger,
    TerraformRoot,
    TerraformScan,
)
from app.services.engine_scores import repo_engine_grades
from tests.fixtures.factories import make_org, make_repo


def _docker_target(db: Session, repo: Repository, path: str) -> DockerTarget:
    target = DockerTarget(repo_id=repo.id, root_path=path)
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def _docker_scan(
    db: Session,
    target: DockerTarget,
    score: float,
    *,
    status: ScanStatus = ScanStatus.completed,
) -> DockerScan:
    scan = DockerScan(
        docker_target_id=target.id,
        status=status,
        score=score,
        triggered_by=ScanTrigger.manual,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def test_no_scans_means_no_grade_for_that_engine(db: Session) -> None:
    """Absent, not zero: an engine that never ran has nothing to report."""
    repo = make_repo(db, make_org(db))
    assert repo_engine_grades(db, [repo.id])[repo.id] == {}


def test_docker_grade_is_the_average_of_its_targets_not_the_worst(
    db: Session,
) -> None:
    """The bug in one assertion.

    The page showed `worstGrade([...])`, so one bad target dragged the header
    down to its grade. Two targets at 90 and 50 average to 70 — not 50.
    """
    repo = make_repo(db, make_org(db))
    _docker_scan(db, _docker_target(db, repo, "a"), 90.0)
    _docker_scan(db, _docker_target(db, repo, "b"), 50.0)

    score, grade = repo_engine_grades(db, [repo.id])[repo.id][Engine.docker]
    assert score == 70.0
    assert grade != "F"


def test_only_the_latest_completed_scan_of_each_target_counts(db: Session) -> None:
    repo = make_repo(db, make_org(db))
    target = _docker_target(db, repo, "a")
    _docker_scan(db, target, 20.0)
    _docker_scan(db, target, 80.0)
    # A failed scan is not a score; it must not drag the average down.
    _docker_scan(db, target, 0.0, status=ScanStatus.failed)

    score, _ = repo_engine_grades(db, [repo.id])[repo.id][Engine.docker]
    assert score == 80.0


def test_engines_are_reported_separately(db: Session) -> None:
    """Each engine's own number, which is the whole point of the field."""
    repo = make_repo(db, make_org(db))
    _docker_scan(db, _docker_target(db, repo, "a"), 40.0)

    root = TerraformRoot(repo_id=repo.id, root_path="infra")
    db.add(root)
    db.commit()
    db.refresh(root)
    db.add(
        TerraformScan(
            terraform_root_id=root.id,
            status=ScanStatus.completed,
            score=95.0,
            triggered_by=ScanTrigger.manual,
        )
    )
    db.commit()

    grades = repo_engine_grades(db, [repo.id])[repo.id]
    assert grades[Engine.docker][0] == 40.0
    assert grades[Engine.terraform][0] == 95.0


def test_another_repos_targets_are_not_counted(db: Session) -> None:
    org = make_org(db)
    mine, theirs = make_repo(db, org), make_repo(db, org)
    _docker_scan(db, _docker_target(db, mine, "a"), 90.0)
    _docker_scan(db, _docker_target(db, theirs, "a"), 10.0)

    grades = repo_engine_grades(db, [mine.id, theirs.id])
    assert grades[mine.id][Engine.docker][0] == 90.0
    assert grades[theirs.id][Engine.docker][0] == 10.0


def test_an_empty_request_asks_nothing(db: Session) -> None:
    assert repo_engine_grades(db, []) == {}


def test_an_unknown_repo_id_reports_no_grades(db: Session) -> None:
    unknown = uuid.uuid4()
    assert repo_engine_grades(db, [unknown]) == {unknown: {}}
