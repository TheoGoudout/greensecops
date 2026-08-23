"""The scan flow the file-based engines share, written once.

``terraform_analysis.py`` and ``docker_analysis.py`` were the same 340-line
function with the nouns swapped: quota gate, fetch, open a scan row, bail out on
an empty target, meter the run, evaluate against OPA, classify a failure, upsert
findings, score, resolve what the scan no longer reports, move the target's
cursor. ``services/engines.py`` had already been created to hold what differs
between those two engines, and the fix-generation and delivery flows had already
been lifted out on the strength of it — the scan flow was simply never moved.

What genuinely differs is small and lives on :class:`EngineSpec`: which document
the files merge into, which rule domain to look up, what a finding's identity is
keyed on, which extra locator columns it carries, and whether the score pools
across the target or averages per file.

Kept **out** of here on purpose:

- ``fetch_files`` and ``analyse`` are passed in per call rather than hung off the
  spec, because they are the seams the tests patch. A worker resolves them from
  its own module globals at call time, so ``patch("…docker_analysis._evaluate")``
  still lands.
- The Celery task, its retry policy and its lock stay in the worker module. They
  are three lines each and reading them next to the task name is worth more than
  the deduplication.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from app.core.db import engine as db_engine
from app.models import (
    AnalysisFailureKind,
    AnalysisTrigger,
    IssueCategory,
    IssueSeverity,
    Repository,
    ScanStatus,
    UsageEngine,
    UsageMeter,
)
from app.services import state_machines as sm
from app.services.billing import quota as billing_quota
from app.services.billing import usage as billing_usage
from app.services.deduplication import compute_fingerprint
from app.services.engines import EngineSpec
from app.services.opa.evaluator import OpaUnavailableError
from app.services.scan_support import load_enabled_rules, resolve_stale_findings
from app.services.scoring import compute_score, score_to_grade

logger = logging.getLogger(__name__)


class ScanFetchError(Exception):
    """Files could not be fetched from GitHub. Transient — the task retries."""


def run_file_scan(
    spec: EngineSpec,
    target_id: str,
    *,
    branch: str,
    commit_sha: str,
    trigger: str,
    billable: bool,
    fetch_files: Callable[..., Sequence[Any]],
    analyse: Callable[[Sequence[Any]], Sequence[Any]],
) -> dict[str, str | int | float]:
    """Scan one target end to end and record the result.

    ``analyse`` takes the fetched files and returns OPA violations; it owns the
    merge into whatever document its engine's rules expect.
    """
    id_key = spec.target_id_field
    with Session(db_engine) as session:
        target = session.get(spec.target_model, uuid.UUID(target_id))
        if not target:
            return {"status": "error", "detail": spec.target_not_found}
        repo = session.get(Repository, target.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        effective_branch = branch or repo.default_branch
        fetch_ref = commit_sha or branch or None

        # Gate before doing any work — including before the GitHub fetch, which
        # is the expensive part. Checked here rather than only in the route
        # because most scans arrive from a push webhook, which has no route.
        if billable and (
            refusal := billing_quota.exhausted_message(
                session, repo.org_id, engine=UsageEngine.of(spec.engine)
            )
        ):
            logger.warning("%s scan refused for %s: %s", spec.label, target_id, refusal)
            return {"status": "quota_exceeded", id_key: target_id, "detail": refusal}

        try:
            fetched = list(fetch_files(repo, target.root_path, ref=fetch_ref))
        except Exception as exc:
            logger.exception(
                "Failed to fetch %s files for %s (%s): %s",
                spec.name,
                repo.full_name,
                target.root_path,
                exc,
            )
            raise ScanFetchError(str(exc)) from exc

        scan = spec.scan_model(
            **{id_key: target.id},
            status=ScanStatus.queued,
            triggered_by=AnalysisTrigger(trigger),
            branch=effective_branch,
            commit_sha=commit_sha or None,
        )
        session.add(scan)
        session.flush()
        sm.advance(scan, sm.ScanMachine, "started")

        if not fetched:
            sm.advance(scan, sm.ScanMachine, "no_targets_found")
            scan.completed_at = datetime.now(timezone.utc)
            session.add(scan)
            session.commit()
            # Deliberately uncharged: an empty target evaluated no rules, and
            # billing for "we looked and there was nothing there" would meter
            # every push to a repo that merely *has* a registered target.
            return {
                "status": "no_targets",
                id_key: target_id,
                "scan_id": str(scan.id),
            }

        if billable:
            billing_usage.record_for_repo(
                session,
                repo=repo,
                meter=UsageMeter.analyses,
                engine=UsageEngine.of(spec.engine),
                source_type=f"{spec.name}_scan",
                source_id=scan.id,
                commit=False,
            )

        try:
            violations = analyse(fetched)
        except Exception as exc:
            logger.exception(
                "OPA evaluation failed for %s target %s: %s",
                spec.name,
                target.root_path,
                exc,
            )
            sm.advance(scan, sm.ScanMachine, "scan_failed")
            scan.error_message = str(exc)[:2000]
            scan.failure_kind = (
                AnalysisFailureKind.transient
                if isinstance(exc, OpaUnavailableError)
                else AnalysisFailureKind.permanent
            )
            scan.completed_at = datetime.now(timezone.utc)
            session.add(scan)
            session.commit()
            return {"status": "failed", id_key: target_id, "scan_id": str(scan.id)}

        seen, per_file, finding_count = _persist_findings(
            session, spec, scan, target, violations
        )
        score = _score(spec, per_file, fetched)
        grade = score_to_grade(score)

        sm.advance(scan, sm.ScanMachine, "succeeded")
        scan.score = score
        scan.grade = grade
        if spec.tracks_file_count:
            scan.file_count = len(fetched)
        scan.completed_at = datetime.now(timezone.utc)
        session.add(scan)
        session.commit()

        resolve_stale_findings(
            session, spec.finding_model, id_key, target.id, seen, spec.name
        )

        target.last_scanned_at = datetime.now(timezone.utc)
        if commit_sha:
            target.last_scanned_head_sha = commit_sha
        session.add(target)
        session.commit()

        logger.info(
            "%s scan complete: target=%s score=%.1f grade=%s findings=%d files=%d",
            spec.label,
            target_id,
            score,
            grade,
            finding_count,
            len(fetched),
        )
        result: dict[str, str | int | float] = {
            "status": "done",
            id_key: target_id,
            "scan_id": str(scan.id),
            "score": round(score, 1),
            "grade": grade,
            "findings": finding_count,
        }
        if spec.tracks_file_count:
            result["files"] = len(fetched)
        return result


def _persist_findings(
    session: Session,
    spec: EngineSpec,
    scan: Any,
    target: Any,
    violations: Sequence[Any],
) -> tuple[set[str], dict[str, list[tuple[str, float]]], int]:
    """Upsert one finding per violation; return what was seen, for scoring.

    Returns ``(fingerprints, severity/weight pairs keyed by file, count)``. The
    fingerprint set is what ``resolve_stale_findings`` diffs against to close
    violations this scan no longer reports.
    """
    rule_map = load_enabled_rules(session, spec.rule_domain)
    seen: set[str] = set()
    per_file: dict[str, list[tuple[str, float]]] = {}
    count = 0

    for v in violations:
        rule = rule_map.get(v.rule_slug)
        if rule is None:
            # Unlike the CI-workflow engine, which auto-registers a rule from
            # the violation that names it, every other engine's rules are seeded
            # from the shipped .rego files ahead of time. An unrecognized slug
            # therefore means a rule shipped without its catalog row — a
            # packaging bug worth surfacing, not silently working around.
            logger.warning(
                "%s violation for unknown rule slug %r — no matching Rule row "
                "(domain=%s); check the rule seeder",
                spec.label,
                v.rule_slug,
                spec.rule_domain.value,
            )
            continue

        fingerprint = compute_fingerprint(
            target.id, rule.id, spec.fingerprint_locator(v), v.discriminator
        )
        seen.add(fingerprint)
        count += 1

        # Locator columns differ per engine: a Terraform finding names a
        # resource address and module path, a Docker one a service or stage.
        extra = spec.finding_columns(v, target)
        shared = {
            "severity": IssueSeverity(v.severity),
            "file_path": v.file_path,
            "line_start": v.line_start,
            "line_end": v.line_end,
            "message": v.message,
            "context": v.context,
        }
        session.execute(
            pg_insert(spec.finding_model)
            .values(
                id=uuid.uuid4(),
                scan_id=scan.id,
                **{spec.target_id_field: target.id},
                rule_id=rule.id,
                fingerprint=fingerprint,
                category=IssueCategory(v.category),
                created_at=datetime.now(timezone.utc),
                **shared,
                **extra,
            )
            .on_conflict_do_update(
                constraint=spec.finding_constraint,
                set_={
                    "scan_id": scan.id,
                    **shared,
                    **extra,
                    # A recurring violation reopens a resolved finding.
                    "resolved_at": None,
                    "resolution_reason": None,
                },
            )
        )
        per_file.setdefault(v.file_path, []).append((v.severity, rule.severity_weight))

    return seen, per_file, count


def _score(
    spec: EngineSpec,
    per_file: dict[str, list[tuple[str, float]]],
    fetched: Sequence[Any],
) -> float:
    """Grade the target, pooling or averaging per file as the engine requires.

    Docker averages; Terraform pools. Not a style difference: a Terraform root is
    one logical module, so pooling its violations is correct. A Docker target is
    N independent files, and pooling makes penalties accumulate across all of
    them — measured against this repository's own eight Docker files, pooling
    scores 0.0 (grade F) where the per-file mean scores 69.6 (grade C). Every
    repo with more than a couple of Dockerfiles would otherwise grade F, which
    tells the user nothing.

    ``compute_score`` already averages per-group scores — that is what it does
    for a workflow's jobs — so files simply take the place jobs occupy there.
    Clean files must be in the mapping or the mean is taken over offenders only,
    and a mostly-clean target scores the same as an entirely dirty one.
    """
    if spec.scores_per_file:
        return compute_score([], {f.path: per_file.get(f.path, []) for f in fetched})
    return compute_score([sv for pairs in per_file.values() for sv in pairs], {})
