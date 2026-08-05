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

Deliberately *not* covered:

- The cloud-posture engine. It has no files, no fixes and no repository — its
  scans hang off an org-level account — so folding it in would mean a spec
  whose fields are half-null for one member.
- The CI-workflow engine. Its files *are* persisted (``WorkflowFile``), so its
  fixes key on a file id rather than a ``(target, path)`` pair, and its
  delivery has to reconcile per-workflow branches. Genuinely a different
  shape, not the same one wearing different names.
- Fetching. Each worker keeps its own ``_fetch_*`` module-level function and
  passes it in, because that is the seam the tests patch.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models import (
    DockerFinding,
    DockerFix,
    DockerTarget,
    TerraformFinding,
    TerraformFix,
    TerraformRoot,
)
from app.services.delivery_pr import docker_fix_branch, tf_fix_branch


@dataclass(frozen=True)
class EngineSpec:
    """The per-engine nouns the shared scan/fix/deliver flows need."""

    # Lowercase identifier, used in commit prefixes ("fix(docker): ...") and
    # error details ("docker_target_not_found").
    name: str
    # Human-readable, used in log lines and PR headings.
    label: str
    # What the user registers to be scanned: a Terraform root, a Docker target.
    target_model: type[Any]
    # Column on the fix/finding rows pointing back at that target.
    target_id_field: str
    finding_model: type[Any]
    fix_model: type[Any]
    # Deterministic PR branch for a target's fixes; the distinct prefixes are
    # what let the frontend tell one engine's PR from another's.
    fix_branch: Callable[[uuid.UUID], str]
    # Names the files this engine rewrites, for the PR body's opening line.
    files_description: str

    @property
    def target_not_found(self) -> str:
        """The API/worker error detail for a missing target."""
        return f"{self.target_model.__tablename__}_not_found"


TERRAFORM_ENGINE = EngineSpec(
    name="terraform",
    label="Terraform",
    target_model=TerraformRoot,
    target_id_field="terraform_root_id",
    finding_model=TerraformFinding,
    fix_model=TerraformFix,
    fix_branch=tf_fix_branch,
    files_description="Terraform files",
)

DOCKER_ENGINE = EngineSpec(
    name="docker",
    label="Docker",
    target_model=DockerTarget,
    target_id_field="docker_target_id",
    finding_model=DockerFinding,
    fix_model=DockerFix,
    fix_branch=docker_fix_branch,
    files_description="Dockerfiles and Compose files",
)
