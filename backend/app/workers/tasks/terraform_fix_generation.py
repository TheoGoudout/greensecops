import uuid

from sqlmodel import Session

from app.core.db import engine
from app.models import TerraformFinding
from app.services.engines import TERRAFORM_ENGINE
from app.services.file_fix_generation import generate_file_fix
from app.services.github.fetch import fetch_terraform_files as _fetch_terraform_files
from app.services.terraform.hcl_parser import parse_terraform_content
from app.workers.celery_app import celery_app

INVALID_HCL_ERROR = "LLM returned invalid Terraform (HCL)"


def _validate(
    file_path: str,
    original: str,  # noqa: ARG001 — the shared guard contract is differential
    content: str,
) -> str | None:
    """Only trust the rewrite if it still parses as HCL; otherwise delivery
    would push a broken ``.tf`` file to the user's branch.

    ``original`` is unused: HCL has no value that must survive byte-identical,
    so there is nothing to diff against. It is in the signature because the
    shared flow's guard contract is differential for Ansible's sake.
    """
    if parse_terraform_content(file_path, content) is None:
        return INVALID_HCL_ERROR
    return None


def _build_prompt(
    file_path: str, file_content: str, findings: list[TerraformFinding]
) -> tuple[str, str]:
    from app.services.llm.terraform_fix_prompt import build_terraform_fix_prompt

    return build_terraform_fix_prompt(
        file_path=file_path, file_content=file_content, findings=findings
    )


@celery_app.task(name="terraform_fix_generation.run", bind=True, max_retries=3)
def run_terraform_fix_generation(
    self: object,  # noqa: ARG001
    finding_ids: list[str],
) -> dict[str, object]:
    """Single LLM call rewriting one ``.tf`` file to fix the given findings.

    The API route creates a pending ``TerraformFix`` per file before queuing
    this task; it consumes that row. All ``finding_ids`` belong to one file of
    one root (the route groups by file path).
    """
    with Session(engine) as session:
        loaded = [session.get(TerraformFinding, uuid.UUID(fid)) for fid in finding_ids]
        findings = [f for f in loaded if f is not None]
        if not findings:
            return {"status": "error", "detail": "no_findings_found"}
        target_id = findings[0].terraform_root_id
        file_path = findings[0].file_path

    return generate_file_fix(
        TERRAFORM_ENGINE,
        target_id,
        file_path,
        findings,
        # Passed in rather than held on the spec: this module-level name is the
        # seam the tests patch.
        _fetch_terraform_files,
        _build_prompt,
        _validate,
    )
