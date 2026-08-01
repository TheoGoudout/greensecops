"""ORM → public-schema mappers for the Docker engine.

Mirrors ``mappers/terraform.py``. The mappers exist so route handlers never
traverse relationships inline — a finding's rule slug and a target's grade are
derived in one place, and the badge route reuses
``latest_completed_docker_scan`` so a target's grade has a single definition.
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
    ScanStatus,
)


def latest_completed_docker_scan(target: DockerTarget) -> DockerScan | None:
    """The target's most recent successfully completed scan, if any.

    A failed or in-flight scan must not define the grade: a target whose latest
    scan errored still has the grade its last good scan produced.
    """
    return max(
        (s for s in target.scans if s.status == ScanStatus.completed),
        key=lambda s: s.created_at or 0,
        default=None,
    )


def to_docker_target_public(target: DockerTarget) -> DockerTargetPublic:
    latest_completed = latest_completed_docker_scan(target)
    badge_sig: str | None = None
    if target.repository and target.repository.is_private:
        # Function-local import: badge_signing imports settings, which pulls in
        # a chunk of the app at module scope — the same dodge
        # mappers/terraform.py uses to avoid a cycle.
        from app.services.badge_signing import sign_docker_target_badge

        badge_sig = sign_docker_target_badge(str(target.id))
    return DockerTargetPublic(
        id=target.id,
        repo_id=target.repo_id,
        repo_full_name=target.repository.full_name if target.repository else None,
        root_path=target.root_path,
        enabled=target.enabled,
        last_scanned_at=target.last_scanned_at,
        last_scanned_head_sha=target.last_scanned_head_sha,
        latest_score=latest_completed.score if latest_completed else None,
        latest_grade=latest_completed.grade if latest_completed else None,
        badge_sig=badge_sig,
    )


def to_docker_scan_public(scan: DockerScan) -> DockerScanPublic:
    return DockerScanPublic(
        id=scan.id,
        docker_target_id=scan.docker_target_id,
        status=scan.status,
        triggered_by=scan.triggered_by,
        branch=scan.branch,
        commit_sha=scan.commit_sha,
        score=scan.score,
        grade=scan.grade,
        file_count=scan.file_count,
        error_message=scan.error_message,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


def to_docker_finding_public(finding: DockerFinding) -> DockerFindingPublic:
    fix = finding.fix
    return DockerFindingPublic(
        id=finding.id,
        scan_id=finding.scan_id,
        docker_target_id=finding.docker_target_id,
        rule_id=finding.rule_id,
        rule_slug=finding.rule.slug if finding.rule else "",
        file_path=finding.file_path,
        service_name=finding.service_name,
        stage_name=finding.stage_name,
        line_start=finding.line_start,
        line_end=finding.line_end,
        severity=finding.severity,
        category=finding.category,
        message=finding.message,
        context=finding.context,
        status=finding.status,
        fix_id=fix.id if fix else None,
        fix_status=fix.status if fix else None,
        created_at=finding.created_at,
        resolved_at=finding.resolved_at,
        resolution_reason=finding.resolution_reason,
    )


def to_docker_fix_public(fix: DockerFix) -> DockerFixPublic:
    pr = fix.pull_request
    return DockerFixPublic(
        id=fix.id,
        docker_target_id=fix.docker_target_id,
        file_path=fix.file_path,
        pr_id=fix.pr_id,
        llm_provider=fix.llm_provider,
        llm_model=fix.llm_model,
        status=fix.status,
        full_content=fix.full_content,
        error_message=fix.error_message,
        pr_url=pr.pr_url if pr else None,
        pr_branch=pr.pr_branch if pr else None,
        pr_state=pr.pr_state if pr else None,
        created_at=fix.created_at,
        delivered_at=fix.delivered_at,
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
    return DockerRuntimeFindingPublic(
        id=enrichment.id,
        telemetry_id=enrichment.telemetry_id,
        rule_slug=enrichment.rule_slug,
        rule_title=rule.title if rule else None,
        severity=rule.severity if rule else None,
        category=rule.category if rule else None,
        evidence=enrichment.evidence,
        recommendation=enrichment.recommendation,
        created_at=enrichment.created_at,
    )


def to_docker_build_telemetry_public(
    telemetry: DockerBuildTelemetry,
    findings: list[DockerRuntimeFindingPublic],
) -> DockerBuildTelemetryPublic:
    return DockerBuildTelemetryPublic(
        id=telemetry.id,
        workflow_run_id=telemetry.workflow_run_id,
        image_ref=telemetry.image_ref,
        dockerfile_path=telemetry.dockerfile_path,
        image_size_bytes=telemetry.image_size_bytes,
        context_size_bytes=telemetry.context_size_bytes,
        build_duration_ms=telemetry.build_duration_ms,
        cache_hit_ratio=telemetry.cache_hit_ratio,
        layers=_decode_json_list(telemetry.layers),
        containers=_decode_json_list(telemetry.containers),
        collected_at=telemetry.collected_at,
        findings=findings,
    )
