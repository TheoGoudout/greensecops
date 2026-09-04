"""ORM → public-schema mappers for the Docker engine.

Mirrors ``mappers/terraform.py``. The mappers exist so route handlers never
traverse relationships inline — a finding's rule slug and a target's grade are
derived in one place, and the badge route reuses ``latest_completed_scan`` so a
target's grade has a single definition.
"""

import json
from typing import Any

from app.models import (
    DockerBuildEnrichment,
    DockerBuildTelemetry,
    DockerBuildTelemetryPublic,
    DockerFinding,
    DockerFindingPublic,
    DockerFix,
    DockerFixPublic,
    DockerRuntimeFindingPublic,
    DockerScan,
    DockerScanPublic,
    DockerTarget,
    DockerTargetPublic,
    Rule,
)
from app.models.enums import TargetActivity
from app.services.badge_signing import sign_badge

from .base import latest_completed_scan, latest_scan_status, to_public


def to_docker_target_public(
    target: DockerTarget,
    activity: TargetActivity = TargetActivity.idle,
) -> DockerTargetPublic:
    # Passed in, not read off the row — see ``to_terraform_root_public``.
    latest = latest_completed_scan(target)
    badge_sig: str | None = None
    if target.repository and target.repository.is_private:
        # Function-local import: badge_signing imports settings, which pulls in
        # a chunk of the app at module scope — the same dodge
        # mappers/terraform.py uses to avoid a cycle.

        badge_sig = sign_badge(str(target.id))
    return to_public(
        target,
        DockerTargetPublic,
        repo_full_name=target.repository.full_name if target.repository else None,
        latest_score=latest.score if latest else None,
        latest_grade=latest.grade if latest else None,
        latest_scan_status=latest_scan_status(target),
        activity=activity,
        badge_sig=badge_sig,
    )


def to_docker_scan_public(scan: DockerScan) -> DockerScanPublic:
    return to_public(scan, DockerScanPublic)


def to_docker_finding_public(finding: DockerFinding) -> DockerFindingPublic:
    fix = finding.fix
    return to_public(
        finding,
        DockerFindingPublic,
        rule_slug=finding.rule.slug if finding.rule else "",
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
    )


def to_docker_fix_public(fix: DockerFix) -> DockerFixPublic:
    pr = fix.pull_request
    return to_public(
        fix,
        DockerFixPublic,
        pr_url=pr.pr_url if pr else None,
        pr_branch=pr.pr_branch if pr else None,
        pr_state=pr.pr_state if pr else None,
    )


def _decode_json_list(raw: str | None) -> list[dict[str, Any]]:
    """Decode a collector-shaped JSON column, tolerating anything malformed.

    These columns are written from the action's payload rather than by the
    backend, so a client that shipped something unexpected must degrade to an
    empty list here rather than 500 the whole tab.
    """
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []


def to_docker_runtime_finding_public(
    enrichment: DockerBuildEnrichment,
    rule: Rule | None = None,
) -> DockerRuntimeFindingPublic:
    """Dress one enrichment with its catalog rule, when it has one.

    ``rule`` is passed in rather than looked up: the caller resolves the whole
    page's slugs in one query, so a tab showing thirty findings does not issue
    thirty selects.
    """
    return to_public(
        enrichment,
        DockerRuntimeFindingPublic,
        rule_title=rule.title if rule else None,
        severity=rule.severity if rule else None,
        category=rule.category if rule else None,
    )


def to_docker_build_telemetry_public(
    telemetry: DockerBuildTelemetry,
    findings: list[DockerRuntimeFindingPublic],
) -> DockerBuildTelemetryPublic:
    return to_public(
        telemetry,
        DockerBuildTelemetryPublic,
        layers=_decode_json_list(telemetry.layers),
        containers=_decode_json_list(telemetry.containers),
        findings=findings,
    )
