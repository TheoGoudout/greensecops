import uuid

from sqlmodel import Session

from app.core.db import engine
from app.models import AnsibleFinding
from app.services.ansible.fix_guard import validate_ansible_fix
from app.services.engines import ANSIBLE_ENGINE
from app.services.file_fix_generation import generate_file_fix
from app.services.github.fetch import fetch_ansible_files as _fetch_ansible_files
from app.workers.celery_app import celery_app


def _validate(file_path: str, original: str, content: str) -> str | None:
    """Reject a rewrite that broke something YAML cannot express.

    Unlike the other two engines this is genuinely differential — see
    ``services/ansible/fix_guard.py``. "Still parses" is not a sufficient gate
    for Ansible: a dropped Jinja expression or a lost ``!vault`` tag parses
    perfectly and silently changes what the play does.
    """
    return validate_ansible_fix(file_path, original, content)


def _build_prompt(
    file_path: str, file_content: str, findings: list[AnsibleFinding]
) -> tuple[str, str]:
    from app.services.llm.ansible_fix_prompt import build_ansible_fix_prompt

    return build_ansible_fix_prompt(
        file_path=file_path, file_content=file_content, findings=findings
    )


@celery_app.task(name="ansible_fix_generation.run", bind=True, max_retries=3)
def run_ansible_fix_generation(
    self: object,  # noqa: ARG001
    finding_ids: list[str],
) -> dict[str, object]:
    """Single LLM call rewriting one Ansible file to fix the given findings.

    The API route creates a pending ``AnsibleFix`` per file before queuing this
    task; it consumes that row. All ``finding_ids`` belong to one file of one
    project (the route groups by file path).
    """
    with Session(engine) as session:
        loaded = [session.get(AnsibleFinding, uuid.UUID(fid)) for fid in finding_ids]
        findings = [f for f in loaded if f is not None]
        if not findings:
            return {"status": "error", "detail": "no_findings_found"}
        target_id = findings[0].ansible_project_id
        file_path = findings[0].file_path

    return generate_file_fix(
        ANSIBLE_ENGINE,
        target_id,
        file_path,
        findings,
        # Passed in rather than held on the spec: this module-level name is the
        # seam the tests patch.
        _fetch_ansible_files,
        _build_prompt,
        _validate,
    )
