import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Fix, FixStatus, Issue, Repository, WorkflowFile
from app.services import state_machines as sm
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.celery_app import celery_app

if TYPE_CHECKING:
    from app.services.llm.base import LLMResponse

logger = logging.getLogger(__name__)

INVALID_YAML_ERROR = "LLM returned invalid YAML"
MISSING_CONTENT_ERROR = "LLM response missing workflow content"


def _is_valid_workflow_yaml(content: str) -> bool:
    """True if ``content`` parses as a YAML mapping (a plausible workflow file)."""
    import yaml

    try:
        return isinstance(yaml.safe_load(content), dict)
    except yaml.YAMLError:
        return False


def restore_trailing_whitespace(original: str, patched: str) -> str:
    """Restore original trailing whitespace on lines that only differ in trailing whitespace.

    LLMs routinely strip trailing whitespace when regenerating file content.
    For lines where the stripped versions are identical, keep the original so
    the delivered diff contains only meaningful changes.
    """
    orig_lines = original.split("\n")
    new_lines = patched.split("\n")
    result = []
    for i, new_line in enumerate(new_lines):
        if (
            i < len(orig_lines)
            and new_line.rstrip() == orig_lines[i].rstrip()
            and new_line != orig_lines[i]
        ):
            result.append(orig_lines[i])
        else:
            result.append(new_line)
    return "\n".join(result)


# ─── Batch coordination ──────────────────────────────────────────────────────
# A repo-wide generation run fans out into one Celery task per workflow file.
# A Redis counter tracks the outstanding tasks so that exactly one aggregated
# fix.ready / fix.failed SSE event pair is published when the last one ends,
# instead of one notification per workflow file.

_BATCH_KEY_TTL = 2 * 60 * 60


def _batch_key(batch_id: str, suffix: str) -> str:
    return f"fixgen:batch:{batch_id}:{suffix}"


def init_fix_batch(batch_id: str, group_count: int) -> None:
    """Register a repo-wide generation run. Fire-and-forget — never raises."""
    try:
        import redis

        from app.core.config import settings

        client = redis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            client.set(
                _batch_key(batch_id, "remaining"), group_count, ex=_BATCH_KEY_TTL
            )
        finally:
            client.close()
    except Exception:
        logger.exception("Failed to init fix batch %s", batch_id)


def _maybe_auto_deliver(repo_id: str, fix_ids: list[str]) -> None:
    """Queue PR delivery for a repo's ready fixes when it has auto_fix_enabled.

    Delivers the repo's *entire* current ready set, not just ``fix_ids``:
    ``fix_ids`` only signals that a delivery is warranted; the full ready set
    is re-queried here so no ready fix is left undelivered.
    """
    try:
        from sqlmodel import col, or_
        from sqlmodel import select as _select

        from app.core.config import settings
        from app.models import PullRequest, PullRequestState, WorkflowFile
        from app.services.delivery_pr import build_delivery_pr_body, repo_fix_branch
        from app.workers.tasks.fix_delivery import deliver_fixes_batch

        with Session(engine) as session:
            repo = session.get(Repository, uuid.UUID(repo_id))
            if not repo or not repo.auto_fix_enabled:
                return

            fixes = list(
                session.exec(
                    _select(Fix)
                    .join(WorkflowFile, Fix.workflow_file_id == WorkflowFile.id)  # type: ignore[arg-type]
                    .where(WorkflowFile.repo_id == repo.id)
                    # Fixes are default-branch-only; never deliver a legacy
                    # feature-branch fix.
                    .where(WorkflowFile.branch == repo.default_branch)
                    .where(Fix.status == FixStatus.ready)
                    .order_by(col(WorkflowFile.path).asc())
                ).all()
            )
            if not fixes:
                return
            fix_ids = [str(f.id) for f in fixes]

            # Reuse the repo's existing open PR branch so the same PR is updated
            # in place. Resolved from the PullRequest directly (not via a fix's
            # pr_id) so a just-regenerated fix, whose link was dropped, still
            # lands on the original PR. A merged PR is excluded — its branch is
            # spent; a fresh PR is opened instead.
            existing_pr = session.exec(
                _select(PullRequest)
                .where(PullRequest.repo_id == repo.id)
                # Exclude comment-mode records (they carry a comment_url but no
                # pr_url) so a PR delivery never reuses their synthetic branch.
                .where(col(PullRequest.pr_url).is_not(None))
                .where(
                    or_(
                        col(PullRequest.pr_state).is_(None),
                        PullRequest.pr_state != PullRequestState.merged,
                    )
                )
                .order_by(
                    PullRequest.updated_at.desc().nulls_last(),  # type: ignore[union-attr]
                    PullRequest.created_at.desc(),  # type: ignore[union-attr]
                )
                .limit(1)
            ).first()
            if existing_pr and existing_pr.externally_modified:
                # The user pushed their own commits onto the fix branch:
                # auto-redelivery would overwrite them. Manual (forced)
                # delivery via the API stays available and clears the flag.
                logger.info(
                    "Skipping auto-delivery for repo %s: PR branch %s was "
                    "modified externally",
                    repo_id,
                    existing_pr.pr_branch,
                )
                return
            pr_branch = (
                existing_pr.pr_branch if existing_pr else repo_fix_branch(repo.id)
            )

            pr_body = build_delivery_pr_body(session, repo.id, fixes, existing_pr)
            deliver_fixes_batch.delay(
                fix_ids=fix_ids,
                repo_id=repo_id,
                pr_branch=pr_branch,
                pr_title=f"fix(ci): apply all {settings.PROJECT_NAME} fixes",
                pr_body=pr_body,
            )
            logger.info(
                "Auto-queued fix delivery: repo=%s fixes=%d", repo_id, len(fixes)
            )
    except Exception:
        logger.exception("Auto-delivery failed for repo %s", repo_id)


def _record_batch_result(
    batch_id: str,
    org_id: str,
    repo_id: str,
    ready_ids: list[str],
    failed_ids: list[str],
    error: str | None,
) -> None:
    """Accumulate one task's results; publish aggregate events when the batch ends.

    Fail-open: if Redis is unavailable the events for this task's fixes are
    published immediately rather than lost.
    """
    try:
        import redis

        from app.core.config import settings

        client = redis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[no-untyped-call]
        try:
            if ready_ids:
                client.sadd(_batch_key(batch_id, "ready"), *ready_ids)
                client.expire(_batch_key(batch_id, "ready"), _BATCH_KEY_TTL)
            if failed_ids:
                client.sadd(_batch_key(batch_id, "failed"), *failed_ids)
                client.expire(_batch_key(batch_id, "failed"), _BATCH_KEY_TTL)
            if error:
                client.set(_batch_key(batch_id, "error"), error, ex=_BATCH_KEY_TTL)

            remaining = client.decr(_batch_key(batch_id, "remaining"))
            if remaining > 0:
                return

            all_ready = sorted(client.smembers(_batch_key(batch_id, "ready")))
            all_failed = sorted(client.smembers(_batch_key(batch_id, "failed")))
            batch_error = client.get(_batch_key(batch_id, "error"))
            client.delete(
                _batch_key(batch_id, "remaining"),
                _batch_key(batch_id, "ready"),
                _batch_key(batch_id, "failed"),
                _batch_key(batch_id, "error"),
            )
        finally:
            client.close()
    except Exception:
        logger.exception("Failed to record batch result for batch %s", batch_id)
        all_ready, all_failed = ready_ids, failed_ids
        batch_error = error

    if all_ready:
        events_pub.publish_event(ev.fix_ready_batch(org_id, repo_id, list(all_ready)))
        _maybe_auto_deliver(repo_id, list(all_ready))
    if all_failed:
        events_pub.publish_event(
            ev.fix_generation_failed_batch(
                org_id, repo_id, list(all_failed), batch_error or "generation failed"
            )
        )


def resolve_llm_provider(repo: Repository) -> tuple[str, str]:
    """Return (provider_str, model_str), cascading repo → org → first available."""
    provider_str = repo.llm_provider.value if repo.llm_provider else None
    model_str = repo.llm_model

    if not provider_str and repo.organization:
        org = repo.organization
        provider_str = (
            org.default_llm_provider.value if org.default_llm_provider else None
        )
        model_str = model_str or org.default_llm_model

    if not provider_str:
        from app.services.llm.catalog import get_first_available_provider

        provider_str, fallback_model = get_first_available_provider()
        model_str = model_str or fallback_model

    if not model_str:
        # Use the provider's own catalog default — an OpenAI model name
        # handed to anthropic/gemini/ollama would fail at request time.
        from app.services.llm.catalog import get_default_model

        model_str = get_default_model(provider_str)

    return provider_str, model_str or "gpt-4o-mini"


def _load_generation_context(
    session: Session,
    issue_ids: list[str],
) -> tuple[list[Issue], WorkflowFile, Repository] | dict[str, object]:
    """Load and validate issues, workflow file, and repo. Returns error dict on failure."""
    loaded = [session.get(Issue, uuid.UUID(iid)) for iid in issue_ids]
    issues = [i for i in loaded if i is not None]
    if not issues:
        return {"status": "error", "detail": "no_issues_found"}

    analysis = issues[0].analysis
    if not analysis:
        return {"status": "error", "detail": "analysis_not_found"}

    wf_file = session.get(WorkflowFile, analysis.workflow_file_id)
    if not wf_file:
        return {"status": "error", "detail": "workflow_file_not_found"}

    repo = session.get(Repository, analysis.repo_id)
    if not repo:
        return {"status": "error", "detail": "repository_not_found"}

    return issues, wf_file, repo


@celery_app.task(name="fix_generation.run", bind=True, max_retries=3)
def run_fix_generation(
    self: object,  # noqa: ARG001
    issue_ids: list[str],
    batch_id: str | None = None,
) -> dict[str, object]:
    """Single LLM call regenerating one workflow file to fix the given issues.

    The API routes create a pending Fix row per workflow file before queuing
    this task; it consumes that row. When ``batch_id`` is set the task is part
    of a repo-wide run and its completion events are aggregated via Redis.
    """
    with Session(engine) as session:
        context = _load_generation_context(session, issue_ids)
        if isinstance(context, dict):
            return context
        issues, wf_file, repo = context

        org_id = str(repo.org_id)
        repo_id_str = str(repo.id)

        # The route creates one pending Fix per workflow file being (re)generated.
        # A workflow file whose fix is in any other state (e.g. a delivered fix
        # kept when force=False) has no pending row and is skipped here.
        fix = session.exec(
            select(Fix)
            .where(Fix.workflow_file_id == wf_file.id)
            .where(Fix.status == FixStatus.pending)
        ).first()
        if fix is None:
            if batch_id:
                _record_batch_result(batch_id, org_id, repo_id_str, [], [], None)
            else:
                events_pub.publish_event(ev.fix_skipped(org_id, repo_id_str))
            return {"status": "skipped", "detail": "no_pending_fix"}

        sm.advance(fix, sm.FixMachine, "start_generation")
        session.add(fix)
        session.commit()
        session.refresh(fix)

        provider_str, model_str = fix.llm_provider.value, fix.llm_model

        if not batch_id:
            events_pub.publish_event(
                ev.fix_generating(
                    org_id,
                    repo_id_str,
                    fix_ids=[str(fix.id)],
                    issue_ids=issue_ids,
                )
            )

        try:
            result = asyncio.run(
                _generate_fixes(
                    workflow_content=wf_file.raw_content,
                    issues=issues,
                    provider_str=provider_str,
                    model_str=model_str,
                    installation_id=repo.installation_id,
                )
            )
        except Exception as exc:
            logger.exception("Fix generation failed for issues %s: %s", issue_ids, exc)
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = str(exc)[:2000]
            session.add(fix)
            session.commit()
            _emit_failure(batch_id, org_id, repo_id_str, str(fix.id), str(exc)[:200])
            return {"status": "failed", "issue_ids": issue_ids}

        full_content = _parse_llm_response(result.content)
        generation_error: str | None = None

        if not full_content:
            generation_error = MISSING_CONTENT_ERROR
        else:
            full_content = restore_trailing_whitespace(
                wf_file.raw_content, full_content
            )
            # Only trust the LLM's rewrite if it is still valid workflow YAML;
            # otherwise delivery would push a corrupt file.
            if not _is_valid_workflow_yaml(full_content):
                logger.warning(
                    "LLM full_content for wf %s is not valid YAML; discarding",
                    wf_file.id,
                )
                generation_error = INVALID_YAML_ERROR

        fix.prompt_tokens = result.prompt_tokens
        fix.completion_tokens = result.completion_tokens
        fix.langsmith_run_id = result.run_id
        if generation_error:
            sm.advance(fix, sm.FixMachine, "generation_failed")
            fix.error_message = generation_error
        else:
            fix.full_content = full_content
            sm.advance(fix, sm.FixMachine, "generation_succeeded")
            # The LLM's own report of which issues it couldn't resolve in this
            # diff. Re-evaluated on every attempt so a retry that succeeds
            # clears a manual-work flag left over from an earlier attempt.
            unfixed = _parse_unfixed_issues(result.content)
            for i, issue in enumerate(issues, start=1):
                issue.needs_manual_work = i in unfixed
                issue.manual_work_note = unfixed.get(i)
                session.add(issue)
        session.add(fix)
        session.commit()

        if fix.status == FixStatus.failed:
            _emit_failure(
                batch_id, org_id, repo_id_str, str(fix.id), generation_error or "no fix"
            )
        elif batch_id:
            _record_batch_result(batch_id, org_id, repo_id_str, [str(fix.id)], [], None)
        else:
            events_pub.publish_event(
                ev.fix_ready(org_id, repo_id_str, str(fix.id), issue_ids)
            )

        logger.info(
            "Fix generation for %d issue(s) in %s: %s, "
            "%d prompt tokens, %d completion tokens",
            len(issues),
            wf_file.path,
            fix.status.value,
            result.prompt_tokens,
            result.completion_tokens,
        )
        return {
            "status": fix.status.value,
            "fix_id": str(fix.id),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        }


def _emit_failure(
    batch_id: str | None, org_id: str, repo_id: str, fix_id: str, error: str
) -> None:
    if batch_id:
        _record_batch_result(batch_id, org_id, repo_id, [], [fix_id], error)
    else:
        events_pub.publish_event(
            ev.fix_generation_failed(org_id, repo_id, fix_id, error)
        )


def _parse_llm_response(content: str) -> str:
    """Extract the full regenerated workflow from the LLM's XML-delimited response."""
    import re

    full_content_match = re.search(
        r"<full_content>\n?(.*?)</full_content>", content, re.DOTALL
    )
    full_content = full_content_match.group(1) if full_content_match else ""

    if not full_content:
        logger.warning(
            "LLM response missing <full_content> block. First 500 chars: %r",
            content[:500],
        )
    logger.info("Parsed LLM response: full_content=%d chars", len(full_content))
    return full_content


def _parse_unfixed_issues(content: str) -> dict[int, str]:
    """Extract the ``<unfixed>`` block: 1-based prompt issue index -> reason.

    Absent or empty block (every issue was fixed) returns ``{}``.
    """
    import re

    match = re.search(r"<unfixed>\n?(.*?)</unfixed>", content, re.DOTALL)
    if not match:
        return {}
    line_re = re.compile(r"^\s*(\d+)\s*:\s*(.+?)\s*$")
    unfixed: dict[int, str] = {}
    for line in match.group(1).splitlines():
        line_match = line_re.match(line)
        if line_match:
            unfixed[int(line_match.group(1))] = line_match.group(2)[:1024]
    return unfixed


def _configure_langchain() -> None:
    from app.core.config import settings

    if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
        os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT


async def _generate_fixes(
    workflow_content: str,
    issues: list[Issue],
    provider_str: str,
    model_str: str,
    installation_id: int | None = None,
) -> "LLMResponse":
    _configure_langchain()

    from app.services.github.sha_resolver import resolve_action_shas
    from app.services.llm.catalog import get_provider
    from app.services.llm.fix_prompt import build_fix_prompt

    gh = None
    if installation_id is not None:
        import redis.asyncio as aioredis

        from app.core.config import settings
        from app.services.github.app_client import GitHubAppClient

        redis_client = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            gh = await GitHubAppClient(redis_client).github_for_installation(
                installation_id
            )
        finally:
            await redis_client.aclose()

    action_sha_map = await resolve_action_shas(workflow_content, gh=gh)
    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_fix_prompt(
        workflow_content=workflow_content,
        issues=issues,
        action_sha_map=action_sha_map or None,
    )
    return await provider.generate(system_prompt, user_prompt)
