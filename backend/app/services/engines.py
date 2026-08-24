"""What differs between the file-based analysis engines, in one place.

Terraform and Docker run the same pipeline — scan a folder in a repo, persist
findings, ask an LLM to rewrite offending files, deliver the rewrites as one
PR — over different file types. Their workers and routes were written by
copying one engine's file and renaming the nouns, which left two near-identical
copies of the delivery flow (97% the same line for line), the generation flow
and most of the route bodies.

:class:`EngineSpec` is those nouns. The flows themselves live once, in
``services/file_fix_delivery.py``, ``services/file_fix_generation.py`` and
``api/engine_routes.py``, and read what they need from a spec.

:class:`EngineSpec` deliberately covers only those two:

- The cloud-posture engine has no files, no fixes and no repository — its scans
  hang off an org-level account — so folding it in would mean a spec whose
  fields are half-null for one member.
- The CI-workflow engine's files *are* persisted (``WorkflowFile``), so its
  fixes key on a file id rather than a ``(target, path)`` pair, and its
  delivery has to reconcile per-workflow branches. Genuinely a different shape,
  not the same one wearing different names.
- Fetching stays out too: each worker keeps its own ``_fetch_*`` module-level
  function and passes it in, because that is the seam the tests patch.

:class:`OverviewSpec` *does* cover all four, because the dashboard's question —
how many targets, how fresh, what grade, how many findings — is one every engine
answers. It lives here rather than in ``api/routes/overview.py`` so that "what
engines are there, and what does each one own?" has a single answer, but it
stays a **separate dataclass**: its consumers (aggregate SQL) and EngineSpec's
(fix generation and delivery) share no field beyond the models, and merging them
would hand cloud and CI a spec that is mostly ``None`` plus an assertion at
every use site.

Both are keyed by :class:`~app.models.enums.Engine`, and ``_SPECS_AGREE`` below
fails at import if the two ever disagree about an engine's models.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_
from sqlmodel import col

from app.models import (
    CloudAccount,
    CloudAccountStatus,
    CloudFinding,
    CloudScan,
    DockerFinding,
    DockerFix,
    DockerScan,
    DockerTarget,
    Engine,
    OverviewSection,
    Repository,
    RuleDomain,
    ScanStatus,
    TerraformFinding,
    TerraformFix,
    TerraformRoot,
    TerraformScan,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
)
from app.services.delivery_pr import docker_fix_branch, tf_fix_branch
from app.services.terraform.hcl_parser import derive_module_path


@dataclass(frozen=True)
class EngineSpec:
    """The per-engine nouns the shared scan/fix/deliver flows need."""

    # Which engine this is. Also the commit prefix ("fix(docker): ...") and the
    # UsageEngine tag, both of which read `engine.value`.
    engine: Engine
    # Human-readable, used in log lines and PR headings.
    label: str
    # What the user calls the thing they registered, for API error details.
    target_label: str
    # What the user registers to be scanned: a Terraform root, a Docker target.
    target_model: type[Any]
    # Column on the fix/finding rows pointing back at that target.
    target_id_field: str
    finding_model: type[Any]
    fix_model: type[Any]
    scan_model: type[Any]
    # Which rules apply. Many-to-one with Engine in general (see
    # ENGINE_OF_DOMAIN), but each *file* engine scans exactly one domain.
    rule_domain: RuleDomain
    # The unique constraint the finding upsert conflicts on.
    finding_constraint: str
    # What a finding's identity is keyed on, beyond target and rule: the thing
    # that stays the same across scans so a dismissal survives a re-run.
    fingerprint_locator: Callable[[Any], str | None]
    # Locator columns only this engine's findings carry, from the violation and
    # its target.
    finding_columns: Callable[[Any, Any], dict[str, Any]]
    # Deterministic PR branch for a target's fixes; the distinct prefixes are
    # what let the frontend tell one engine's PR from another's.
    fix_branch: Callable[[uuid.UUID], str]
    # Names the files this engine rewrites, for the PR body's opening line.
    files_description: str
    # Whether the grade averages per file rather than pooling across the target,
    # and whether the scan row counts the files it saw. Both are Docker's, and
    # `services/scan_runner._score` explains why.
    scores_per_file: bool = False
    tracks_file_count: bool = False

    @property
    def name(self) -> str:
        """The engine's identifier as a string, for log lines and commit prefixes."""
        return self.engine.value

    @property
    def target_not_found(self) -> str:
        """The API/worker error detail for a missing target."""
        return f"{self.target_model.__tablename__}_not_found"


def _terraform_finding_columns(v: Any, root: Any) -> dict[str, Any]:
    """Terraform's locator columns: where in the module tree the resource sits."""

    module_path = derive_module_path(v.file_path, root.root_path)
    return {
        "resource_address": v.resource_address,
        "module_path": module_path,
        "terraform_address": terraform_address(module_path, v.resource_address),
    }


def terraform_address(
    module_path: str | None, resource_address: str | None
) -> str | None:
    """Full Terraform address for a finding, module prefix included.

    Prefixes the resource address (``aws_s3_bucket.logs``) with a single
    ``module.`` segment carrying the directory-derived module path, with ``/``
    rewritten to ``.``: path ``modules/storage`` yields
    ``module.modules.storage.aws_s3_bucket.logs``. A single prefix — not one per
    path segment — because the path is a directory locator, not a resolved
    ``module {}`` invocation chain (see ``derive_module_path``), so the segments
    after ``module.`` are a path, not a nesting chain.

    Root-module resources (no ``module_path``) get the bare resource address;
    returns ``None`` only when the rule emitted no resource address at all.
    """
    if resource_address is None:
        return None
    if not module_path:
        return resource_address
    return f"module.{module_path.replace('/', '.')}.{resource_address}"


TERRAFORM_ENGINE = EngineSpec(
    engine=Engine.terraform,
    label="Terraform",
    target_label="Terraform root",
    target_model=TerraformRoot,
    target_id_field="terraform_root_id",
    finding_model=TerraformFinding,
    fix_model=TerraformFix,
    scan_model=TerraformScan,
    rule_domain=RuleDomain.iac_terraform,
    finding_constraint="uq_terraform_finding_root_fingerprint",
    # A resource keeps its address across scans even when its file moves.
    fingerprint_locator=lambda v: v.resource_address,
    finding_columns=_terraform_finding_columns,
    fix_branch=tf_fix_branch,
    files_description="Terraform files",
)

DOCKER_ENGINE = EngineSpec(
    engine=Engine.docker,
    label="Docker",
    target_label="Docker target",
    target_model=DockerTarget,
    target_id_field="docker_target_id",
    finding_model=DockerFinding,
    fix_model=DockerFix,
    scan_model=DockerScan,
    rule_domain=RuleDomain.container_docker,
    finding_constraint="uq_docker_finding_target_fingerprint",
    # No resource addresses here — a Docker rule fires on a file, and the
    # service or stage within it is carried as a column rather than as identity.
    fingerprint_locator=lambda v: v.file_path,
    finding_columns=lambda v, _target: {
        "service_name": v.service_name,
        "stage_name": v.stage_name,
    },
    fix_branch=docker_fix_branch,
    files_description="Dockerfiles and Compose files",
    scores_per_file=True,
    tracks_file_count=True,
)


# ─── Dashboard aggregation ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OverviewSpec:
    """The per-engine nouns the aggregation below needs, as column objects.

    Column objects rather than attribute-name strings so mypy and SQLModel can
    still see the types; the alternative degrades the whole module to
    stringly-typed ``getattr`` access for the sake of four lines.
    """

    key: Engine
    section: OverviewSection
    label: str

    target_model: type[Any]
    scan_model: type[Any]
    finding_model: type[Any]
    # ``None`` for cloud: CloudFinding carries no fix_id, there is no pipeline.
    fix_model: type[Any] | None

    scan_target_fk: Any
    scan_completed: Any
    scan_failed: Any
    # CI orders its "latest scan" by completed_at first, everyone else by
    # created_at. Not a stylistic difference — see `_latest_scan_order`.
    scan_orders_by_completed_at: bool

    finding_target_fk: Any
    finding_scan_fk: Any
    # Predicate marking a target as "switched on". Not a plain column: Docker
    # and Terraform have a bool, cloud has a status enum, CI has neither.
    target_enabled: Any | None
    # (model, onclause) the target query must join for `target_extra` to work.
    target_join: tuple[type[Any], Any] | None
    target_extra: Any | None


OVERVIEW_SPECS: list[OverviewSpec] = [
    OverviewSpec(
        key=Engine.workflow,
        section=OverviewSection.ci,
        label="CI workflows",
        target_model=WorkflowFile,
        scan_model=WorkflowScan,
        finding_model=WorkflowFinding,
        fix_model=WorkflowFix,
        scan_target_fk=WorkflowScan.workflow_file_id,
        scan_completed=ScanStatus.completed,
        scan_failed=ScanStatus.failed,
        scan_orders_by_completed_at=True,
        finding_target_fk=WorkflowFinding.workflow_file_id,
        finding_scan_fk=WorkflowFinding.analysis_id,
        # A workflow file has no enable switch; `enabled` falls back to
        # `total` for this engine.
        target_enabled=None,
        target_join=(Repository, WorkflowFile.repo_id == Repository.id),
        # Same scoping compute_avg_scores_batch applies (scoring.py:113-118):
        # without it, feature-branch and deleted workflow files inflate
        # every CI count on the dashboard.
        target_extra=and_(
            col(WorkflowFile.branch) == Repository.default_branch,
            col(WorkflowFile.deleted_at).is_(None),
        ),
    ),
    OverviewSpec(
        key=Engine.docker,
        section=OverviewSection.docker,
        label="Docker",
        target_model=DockerTarget,
        scan_model=DockerScan,
        finding_model=DockerFinding,
        fix_model=DockerFix,
        scan_target_fk=DockerScan.docker_target_id,
        scan_completed=ScanStatus.completed,
        scan_failed=ScanStatus.failed,
        scan_orders_by_completed_at=False,
        finding_target_fk=DockerFinding.docker_target_id,
        finding_scan_fk=DockerFinding.scan_id,
        target_enabled=col(DockerTarget.enabled).is_(True),
        target_join=None,
        target_extra=None,
    ),
    OverviewSpec(
        key=Engine.terraform,
        section=OverviewSection.infra,
        label="Terraform",
        target_model=TerraformRoot,
        scan_model=TerraformScan,
        finding_model=TerraformFinding,
        fix_model=TerraformFix,
        scan_target_fk=TerraformScan.terraform_root_id,
        scan_completed=ScanStatus.completed,
        scan_failed=ScanStatus.failed,
        scan_orders_by_completed_at=False,
        finding_target_fk=TerraformFinding.terraform_root_id,
        finding_scan_fk=TerraformFinding.scan_id,
        target_enabled=col(TerraformRoot.enabled).is_(True),
        target_join=None,
        target_extra=None,
    ),
    OverviewSpec(
        key=Engine.cloud,
        section=OverviewSection.infra,
        label="Cloud posture",
        target_model=CloudAccount,
        scan_model=CloudScan,
        finding_model=CloudFinding,
        fix_model=None,
        scan_target_fk=CloudScan.cloud_account_id,
        scan_completed=ScanStatus.completed,
        scan_failed=ScanStatus.failed,
        scan_orders_by_completed_at=False,
        finding_target_fk=CloudFinding.cloud_account_id,
        finding_scan_fk=CloudFinding.scan_id,
        target_enabled=CloudAccount.status == CloudAccountStatus.connected,
        target_join=None,
        target_extra=None,
    ),
]


# EngineSpec and OverviewSpec describe overlapping engines from different
# angles; where both speak about one engine they must mean the same tables.
# A silent disagreement would show the dashboard one engine's findings under
# another's heading, which no test would notice.
_FILE_FIX_SPECS: dict[Engine, EngineSpec] = {
    spec.engine: spec for spec in (TERRAFORM_ENGINE, DOCKER_ENGINE)
}

for _ov in OVERVIEW_SPECS:
    _fx = _FILE_FIX_SPECS.get(_ov.key)
    if _fx is not None:
        assert _ov.target_model is _fx.target_model, _ov.key
        assert _ov.finding_model is _fx.finding_model, _ov.key
        assert _ov.fix_model is _fx.fix_model, _ov.key
assert {s.engine for s in _FILE_FIX_SPECS.values()} <= {s.key for s in OVERVIEW_SPECS}
