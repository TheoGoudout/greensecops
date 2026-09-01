"""A repository's current findings for one engine, as a SARIF log.

``services/sarif.py`` knows the format; this knows where the findings live.
The split is the point: the format has one implementation for every engine, so
"how severe is this" cannot acquire a per-engine answer, while the query that
reaches a repository's findings genuinely does differ — the CI-workflow engine
stores its files as rows and the others carry a path on the finding.

Only the file engines are here. The cloud engine's findings are about live
resources in an AWS account, not lines in the checkout Code Scanning is
annotating, so there is nothing for GitHub to point at; a SARIF result with no
location is dropped on upload, and one pointed at an invented path would be a
lie about the repository. That exclusion is deliberate rather than pending.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, col, select

from app.__version__ import __version__
from app.core.config import settings
from app.models import (
    AnsibleFinding,
    AnsibleProject,
    DockerFinding,
    DockerTarget,
    Engine,
    FindingStatus,
    Repository,
    Rule,
    TerraformFinding,
    TerraformRoot,
    WorkflowFile,
    WorkflowFinding,
)
from app.services.sarif import SarifFinding, build_sarif

# What the report calls itself. The name is what GitHub labels the alerts with
# and what a team sees in the security tab's tool filter, so it is the product
# name rather than the module's.
TOOL_NAME = settings.PROJECT_NAME
TOOL_INFORMATION_URI = settings.MARKETING_URL


@dataclass(frozen=True)
class SarifSpec:
    """Where one engine keeps the findings a repository's report is built from.

    A third spec beside ``EngineSpec`` and ``OverviewSpec`` for the same reason
    those two are separate: the fields it needs — how to reach a repo's
    findings and where the file path is — are ones neither of the others
    carries, and bolting them on would leave both half-populated. It covers the
    four file engines; see the module docstring for why cloud is not one.
    """

    engine: Engine
    finding_model: type[Any]
    # The target table a finding is reached through, and the join back to it.
    # Workflow joins ``WorkflowFile`` (its files are rows); the others join the
    # target they were registered against.
    target_model: type[Any]
    join_on: Any
    # ``(file_path, line_start, line_end)`` for one ``(finding, target)`` pair.
    # Terraform and Ansible paths are already repository-relative; Docker's are
    # too. Workflow's lives on the joined file row.
    locate: Callable[[Any, Any], tuple[str, int | None, int | None]]


def _file_from_target(finding: Any, _target: Any) -> tuple[str, int | None, int | None]:
    return finding.file_path, finding.line_start, finding.line_end


def _file_from_workflow_row(
    finding: Any, workflow_file: Any
) -> tuple[str, int | None, int | None]:
    """The CI engine's path comes from the ``WorkflowFile`` row it scanned."""
    return workflow_file.path, finding.line_start, finding.line_end


SARIF_SPECS: dict[Engine, SarifSpec] = {
    Engine.workflow: SarifSpec(
        engine=Engine.workflow,
        finding_model=WorkflowFinding,
        target_model=WorkflowFile,
        join_on=WorkflowFinding.workflow_file_id == WorkflowFile.id,
        locate=_file_from_workflow_row,
    ),
    Engine.terraform: SarifSpec(
        engine=Engine.terraform,
        finding_model=TerraformFinding,
        target_model=TerraformRoot,
        join_on=TerraformFinding.terraform_root_id == TerraformRoot.id,
        locate=_file_from_target,
    ),
    Engine.docker: SarifSpec(
        engine=Engine.docker,
        finding_model=DockerFinding,
        target_model=DockerTarget,
        join_on=DockerFinding.docker_target_id == DockerTarget.id,
        locate=_file_from_target,
    ),
    Engine.ansible: SarifSpec(
        engine=Engine.ansible,
        finding_model=AnsibleFinding,
        target_model=AnsibleProject,
        join_on=AnsibleFinding.ansible_project_id == AnsibleProject.id,
        locate=_file_from_target,
    ),
}


def collect_findings(
    session: Session, repo_id: uuid.UUID, spec: SarifSpec
) -> list[SarifFinding]:
    """Every finding a repository currently has open for one engine.

    Open only: a resolved finding is one the repository no longer has, and a
    finding the team ignored is one they told us not to raise. Including either
    would re-open in the security tab exactly what was already dealt with here
    — the two views would then disagree about the same finding, which is worse
    than the report being empty.
    """
    rows = session.exec(
        select(spec.finding_model, spec.target_model, Rule)
        .join(spec.target_model, spec.join_on)
        .join(Rule, spec.finding_model.rule_id == Rule.id)
        .where(spec.target_model.repo_id == repo_id)
        .where(spec.finding_model.status == FindingStatus.open)
        .order_by(col(Rule.slug))
    ).all()

    findings: list[SarifFinding] = []
    for finding, target, rule in rows:
        file_path, line_start, line_end = spec.locate(finding, target)
        if not file_path:
            # Nothing to annotate. Dropped rather than anchored somewhere
            # arbitrary: a result whose location is wrong is worse than one
            # that is missing, because it sends a reviewer to innocent code.
            continue
        findings.append(
            SarifFinding(
                rule_slug=rule.slug,
                rule_title=rule.title,
                rule_description=rule.description,
                severity=finding.severity,
                category=finding.category,
                message=finding.message,
                file_path=file_path.lstrip("/"),
                line_start=line_start,
                line_end=line_end,
                fingerprint=finding.fingerprint,
            )
        )
    return findings


def sarif_for_repository(
    session: Session, repo: Repository, engine: Engine
) -> dict[str, Any]:
    """The SARIF log ``upload-sarif`` should be handed for this repo and engine."""
    spec = SARIF_SPECS[engine]
    return build_sarif(
        collect_findings(session, repo.id, spec),
        tool_name=f"{TOOL_NAME} ({engine.value})",
        tool_version=__version__,
        information_uri=TOOL_INFORMATION_URI,
    )


def sarif_engines() -> Sequence[Engine]:
    """The engines a SARIF report can be produced for."""
    return tuple(SARIF_SPECS)
