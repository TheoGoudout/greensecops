import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Repository, TerraformFinding, TerraformFix, TerraformRoot
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.terraform.hcl_parser import parse_terraform_content
from app.workers.celery_app import celery_app
from app.workers.tasks.fix_generation import (
    _parse_llm_response,
    _parse_unfixed_issues,
    restore_trailing_whitespace,
)
from app.workers.tasks.terraform_analysis import _fetch_terraform_files

if TYPE_CHECKING:
    from app.services.llm.base import LLMResponse

logger = logging.getLogger(__name__)

INVALID_HCL_ERROR = "LLM returned invalid Terraform (HCL)"
MISSING_CONTENT_ERROR = "LLM response missing Terraform content"
FILE_NOT_FOUND_ERROR = "Terraform file no longer present in the root"


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

        root = session.get(TerraformRoot, findings[0].terraform_root_id)
        if not root:
            return {"status": "error", "detail": "terraform_root_not_found"}
        repo = session.get(Repository, root.repo_id)
        if not repo:
            return {"status": "error", "detail": "repository_not_found"}

        file_path = findings[0].file_path

        # The route creates one pending fix per (root, file). A file whose fix is
        # in any other state has no pending row and is skipped here.
        fix = session.exec(
            select(TerraformFix)
            .where(TerraformFix.terraform_root_id == root.id)
            .where(TerraformFix.file_path == file_path)
            .where(TerraformFix.status == FixStatus.pending)
        ).first()
        if fix is None:
            return {"status": "skipped", "detail": "no_pending_fix"}

        sm.advance(fix, sm.FixMachine, "start_generation")
        session.add(fix)
        session.commit()
        session.refresh(fix)

        # Fetch the file's current source live from GitHub (Terraform files
        # aren't persisted — same fetch the scan worker uses).
        try:
            fetched = _fetch_terraform_files(repo, root.root_path)
        except Exception as exc:
            logger.exception(
                "Failed to fetch terraform files for fix %s: %s", fix.id, exc
            )
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = str(exc)[:2000]
            session.add(fix)
            session.commit()
            return {"status": "failed", "fix_id": str(fix.id)}

        source = next((f for f in fetched if f.path == file_path), None)
        if source is None:
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = FILE_NOT_FOUND_ERROR
            session.add(fix)
            session.commit()
            return {"status": "failed", "fix_id": str(fix.id)}

        try:
            result = asyncio.run(
                _generate_terraform_fix(
                    file_path=file_path,
                    file_content=source.content,
                    findings=findings,
                    provider_str=fix.llm_provider.value,
                    model_str=fix.llm_model,
                )
            )
        except Exception as exc:
            logger.exception("Terraform fix generation failed for %s: %s", fix.id, exc)
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = str(exc)[:2000]
            session.add(fix)
            session.commit()
            return {"status": "failed", "fix_id": str(fix.id)}

        full_content = _parse_llm_response(result.content)
        generation_error: str | None = None
        if not full_content:
            generation_error = MISSING_CONTENT_ERROR
        else:
            full_content = restore_trailing_whitespace(source.content, full_content)
            # Only trust the rewrite if it still parses as HCL; otherwise
            # delivery would push a broken .tf file.
            if parse_terraform_content(file_path, full_content) is None:
                logger.warning(
                    "LLM full_content for terraform file %s is not valid HCL; "
                    "discarding",
                    file_path,
                )
                generation_error = INVALID_HCL_ERROR

        fix.prompt_tokens = result.prompt_tokens
        fix.completion_tokens = result.completion_tokens
        fix.langsmith_run_id = result.run_id
        if generation_error:
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = generation_error
        else:
            fix.full_content = full_content
            sm.advance(fix, sm.FixMachine, "generation_succeeded")
            # Parsed for parity with the workflow flow; Terraform findings carry
            # no manual-work flag yet, so it's informational only.
            _parse_unfixed_issues(result.content)
        session.add(fix)
        session.commit()

        logger.info(
            "Terraform fix generation for %d finding(s) in %s: %s",
            len(findings),
            file_path,
            fix.status.value,
        )
        return {"status": fix.status.value, "fix_id": str(fix.id)}


async def _generate_terraform_fix(
    file_path: str,
    file_content: str,
    findings: list[TerraformFinding],
    provider_str: str,
    model_str: str,
) -> "LLMResponse":
    from app.services.llm.catalog import get_provider
    from app.services.llm.terraform_fix_prompt import build_terraform_fix_prompt

    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_terraform_fix_prompt(
        file_path=file_path,
        file_content=file_content,
        findings=findings,
    )
    return await provider.generate(system_prompt, user_prompt)
