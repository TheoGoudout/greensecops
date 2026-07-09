import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from ruamel.yaml import YAML
from sqlmodel import Session, select

from app import crud
from app.api.deps import (
    CurrentUser,
    GitHubAppClientDep,
    SessionDep,
    authorize_repo,
    get_current_active_superuser,
)
from app.api.mappers import to_repo_public
from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    ExternalRepositoryCreate,
    OrgMember,
    Repository,
    RepositoryPublic,
    User,
    WorkflowFile,
    WorkflowFilePublic,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.scoring import average_latest_scores, score_to_grade

SuperuserDep = Annotated[User, Depends(get_current_active_superuser)]


router = APIRouter(prefix="/repositories", tags=["repositories"])


def _get_repo_for_user(
    repo_id: uuid.UUID, session: Session, current_user: User
) -> Repository:
    return authorize_repo(session, current_user, repo_id)


def _compute_repo_grade(
    session: Session, repo_id: uuid.UUID
) -> tuple[float | None, str | None, int]:
    """Return (avg_score, grade, workflow_count) from latest analyses per workflow file."""
    analyses = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.status == AnalysisStatus.completed)
        .where(Analysis.score.isnot(None))  # type: ignore[union-attr]
        .order_by(Analysis.workflow_file_id, Analysis.created_at.desc())  # type: ignore[arg-type]
    ).all()

    avg, count = average_latest_scores(list(analyses))
    if avg is None:
        return None, None, 0
    return round(avg, 1), score_to_grade(avg), count


def _compute_grades_batch(
    session: Session, repo_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[float | None, str | None]]:
    """Batch-compute (avg_score, grade) for multiple repos in a single query."""
    if not repo_ids:
        return {}

    analyses = session.exec(
        select(Analysis)
        .where(Analysis.repo_id.in_(repo_ids))  # type: ignore[attr-defined]
        .where(Analysis.status == AnalysisStatus.completed)
        .where(Analysis.score.isnot(None))  # type: ignore[union-attr]
        .order_by(Analysis.workflow_file_id, Analysis.created_at.desc())  # type: ignore[arg-type]
    ).all()

    seen: set[uuid.UUID] = set()
    scores_by_repo: dict[uuid.UUID, list[float]] = defaultdict(list)
    for a in analyses:
        if a.workflow_file_id not in seen:
            seen.add(a.workflow_file_id)
            if a.score is not None:
                scores_by_repo[a.repo_id].append(a.score)  # type: ignore[arg-type]

    result: dict[uuid.UUID, tuple[float | None, str | None]] = {}
    for repo_id in repo_ids:
        scores = scores_by_repo.get(repo_id, [])
        if scores:
            avg = round(sum(scores) / len(scores), 1)
            result[repo_id] = (avg, score_to_grade(avg))
        else:
            result[repo_id] = (None, None)
    return result


@router.get("/", response_model=list[RepositoryPublic])
def list_repositories(
    session: SessionDep,
    current_user: CurrentUser,
    org_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[RepositoryPublic]:
    query = select(Repository)
    if not current_user.is_superuser:
        query = query.where(
            Repository.org_id.in_(  # type: ignore[attr-defined]
                select(OrgMember.org_id).where(OrgMember.user_id == current_user.id)
            )
        )
    if org_id:
        query = query.where(Repository.org_id == org_id)
    if enabled is not None:
        query = query.where(Repository.enabled == enabled)
    query = query.order_by(Repository.full_name).offset(skip).limit(limit)  # type: ignore[arg-type]
    repos = list(session.exec(query).all())
    grades = _compute_grades_batch(session, [r.id for r in repos])
    return [to_repo_public(r, *grades.get(r.id, (None, None))) for r in repos]


@router.get("/external", response_model=list[RepositoryPublic])
def list_external_repositories(
    session: SessionDep,
    _superuser: SuperuserDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[RepositoryPublic]:
    repos = list(
        session.exec(
            select(Repository)
            .where(Repository.is_external == True)  # noqa: E712
            .order_by(Repository.full_name)  # type: ignore[arg-type]
            .offset(skip)
            .limit(limit)
        ).all()
    )
    grades = _compute_grades_batch(session, [r.id for r in repos])
    return [to_repo_public(r, *grades.get(r.id, (None, None))) for r in repos]


@router.post("/external", response_model=RepositoryPublic, status_code=201)
async def create_external_repository(
    body: ExternalRepositoryCreate,
    session: SessionDep,
    _superuser: SuperuserDep,
    github_client: GitHubAppClientDep,
) -> RepositoryPublic:
    owner = body.full_name.split("/")[0]

    if body.installation_id is not None:
        repos = await github_client.list_installation_repositories(body.installation_id)
        target = next(
            (r for r in repos if r.full_name.lower() == body.full_name.lower()), None
        )
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"Repository '{body.full_name}' not found in installation {body.installation_id}",
            )
    else:
        try:
            target = await github_client.fetch_public_repo_info(body.full_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    existing = session.exec(
        select(Repository).where(Repository.github_repo_id == target.github_repo_id)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Repository already exists")

    org = crud.upsert_organization(
        session=session,
        github_org_id=None,
        name=owner,
        installation_id=None,
    )
    repo = Repository(
        org_id=org.id,
        github_repo_id=target.github_repo_id,
        full_name=target.full_name,
        installation_id=body.installation_id,
        default_branch=target.default_branch,
        enabled=True,
        is_external=True,
    )
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return to_repo_public(repo, None, None)


@router.get("/{repo_id}", response_model=RepositoryPublic)
def get_repository(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> RepositoryPublic:
    repo = _get_repo_for_user(repo_id, session, current_user)
    avg_score, grade, _ = _compute_repo_grade(session, repo_id)
    return to_repo_public(repo, avg_score, grade)


@router.get("/{repo_id}/workflow-files", response_model=list[WorkflowFilePublic])
def list_workflow_files(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> list[WorkflowFilePublic]:
    repo = _get_repo_for_user(repo_id, session, current_user)
    wf_files = session.exec(
        select(WorkflowFile).where(WorkflowFile.repo_id == repo.id)
    ).all()
    return [
        WorkflowFilePublic(
            id=wf.id,
            path=wf.path,
            raw_content=wf.raw_content,
        )
        for wf in wf_files
    ]


@router.patch("/{repo_id}/toggle")
def toggle_repository(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    enabled: bool,
) -> dict[str, str | bool]:
    repo = _get_repo_for_user(repo_id, session, current_user)
    repo.enabled = enabled
    session.add(repo)
    session.commit()
    events_pub.publish_event(
        ev.repository_toggled(str(repo.org_id), str(repo_id), enabled)
    )
    return {"repo_id": str(repo_id), "enabled": enabled}


@router.patch("/{repo_id}/auto-fix")
def toggle_auto_fix(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    enabled: bool,
) -> dict[str, str | bool]:
    repo = _get_repo_for_user(repo_id, session, current_user)
    repo.auto_fix_enabled = enabled
    session.add(repo)
    session.commit()
    return {"repo_id": str(repo_id), "auto_fix_enabled": enabled}


@router.get("/{repo_id}/branches", response_model=list[str])
def list_repository_branches(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[str]:
    from sqlmodel import col

    from app.models import Analysis, AnalysisStatus

    _get_repo_for_user(repo_id, session, current_user)
    branches = session.exec(
        select(col(Analysis.branch))
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.status == AnalysisStatus.completed)
        .where(col(Analysis.branch).isnot(None))
        .distinct()
        .order_by(col(Analysis.branch))
    ).all()
    return [b for b in branches if b]


def _inject_action_into_workflow(raw_content: str) -> tuple[str, bool]:
    """Parse workflow YAML to find insertion points, then insert the action step as raw text.

    Uses ruamel.yaml only for parsing (to get line numbers and detect duplicates).
    Serialization is text-based so the PR diff contains only the inserted lines.
    Also injects `permissions: id-token: write` into each modified job, since the
    action authenticates via GitHub OIDC and requires that permission.
    Returns (new_content, was_modified).
    """
    yaml_rt = YAML()
    try:
        workflow = yaml_rt.load(raw_content)
    except Exception:
        return raw_content, False

    if not isinstance(workflow, dict):
        return raw_content, False

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return raw_content, False

    action_prefix = settings.GITHUB_ACTION_REF.split("@")[0]

    # All text insertions as (line_index, text) pairs — processed in reverse order.
    all_insertions: list[tuple[int, str]] = []

    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            continue

        already_present = any(
            isinstance(s, dict) and str(s.get("uses", "")).startswith(action_prefix)
            for s in steps
        )

        if not already_present:
            try:
                first_step_line, first_step_val_col = steps.lc.data[0]
            except (AttributeError, KeyError, IndexError):
                continue
            # lc.data stores the column of the value (after "- "), so dash is 2 columns earlier.
            col = first_step_val_col - 2
            indent = " " * col
            default_url = settings.GREENSECOPS_PUBLIC_URL or settings.BACKEND_HOST
            step_text = (
                f"{indent}- name: {settings.PROJECT_NAME} Telemetry\n"
                f"{indent}  uses: {settings.GITHUB_ACTION_REF}\n"
                f"{indent}  with:\n"
                f"{indent}    greensecops_url: ${{{{ vars.GREENSECOPS_URL || '{default_url}' }}}}\n"
            )
            all_insertions.append((first_step_line, step_text))

        # Inject `permissions: id-token: write` for this job if not already set.
        # Required because the action uses GitHub OIDC for authentication.
        permissions = job.get("permissions")
        if isinstance(permissions, dict):
            if permissions.get("id-token") != "write":
                try:
                    perm_line = job.lc.data["permissions"][0]
                    perm_col = job.lc.data["permissions"][1]
                    perm_value_indent = " " * (perm_col + 2)
                    all_insertions.append(
                        (perm_line + 1, f"{perm_value_indent}id-token: write\n")
                    )
                except (AttributeError, KeyError, TypeError):
                    pass
        elif permissions is None:
            try:
                steps_line = job.lc.data["steps"][0]
                steps_col = job.lc.data["steps"][1]
                job_indent = " " * steps_col
                perm_block = (
                    f"{job_indent}permissions:\n{job_indent}  id-token: write\n"
                )
                all_insertions.append((steps_line, perm_block))
            except (AttributeError, KeyError, TypeError):
                pass

    if not all_insertions:
        return raw_content, False

    lines = raw_content.splitlines(keepends=True)
    # Process in reverse order so earlier line numbers stay valid after insertions.
    for line_idx, text in sorted(all_insertions, key=lambda x: x[0], reverse=True):
        lines[line_idx:line_idx] = text.splitlines(keepends=True)

    return "".join(lines), True


async def _inject_badge_via_llm(
    readme_content: str, badge_markdown: str, repo: Repository
) -> str | None:
    """Use the LLM to intelligently place a badge in README content.

    Returns the modified README content, or None on failure.
    """
    from app.services.llm.badge_prompt import build_badge_prompt
    from app.services.llm.catalog import get_provider

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

    provider = get_provider(provider=provider_str, model=model_str)
    system_prompt, user_prompt = build_badge_prompt(readme_content, badge_markdown)
    result = await provider.generate(system_prompt, user_prompt)
    return result.content


def _badge_only_added(original: str, modified: str) -> bool:
    """Return True if modified differs from original only by pure insertions (no deletes/replaces)."""
    import difflib

    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)
    for tag, _i1, _i2, _j1, _j2 in difflib.SequenceMatcher(
        None, orig_lines, mod_lines
    ).get_opcodes():
        if tag in ("equal", "insert"):
            continue
        return False
    return True


def _insert_badge_simple(readme_content: str, badge_markdown: str) -> str:
    """Insert badge after the first top-level heading, or prepend to the file."""
    import re

    match = re.search(r"^(#[^\n]*\n)", readme_content, re.MULTILINE)
    if match:
        pos = match.end()
        return (
            readme_content[:pos] + "\n" + badge_markdown + "\n" + readme_content[pos:]
        )
    return badge_markdown + "\n\n" + readme_content


@router.post("/{repo_id}/integrate-action", status_code=202)
async def integrate_action(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    github_client: GitHubAppClientDep,
) -> dict[str, str]:
    import logging

    from github import Auth, Github
    from github.GithubException import GithubException

    from app.services.github.fix_delivery import FixDeliveryService

    logger = logging.getLogger(__name__)
    app_name = settings.PROJECT_NAME

    repo = _get_repo_for_user(repo_id, session, current_user)

    workflow_files = repo.workflow_files
    if not workflow_files:
        raise HTTPException(
            status_code=404, detail="No workflow files found for this repository"
        )

    if repo.installation_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"Repository has no GitHub App installation — ask the repo owner to install the {app_name} GitHub App first",
        )

    token = await github_client.get_installation_token(repo.installation_id)
    gh_repo = Github(auth=Auth.Token(token)).get_repo(repo.full_name)
    branch = repo.default_branch or "main"

    # Use live file content from the base branch so the PR diff is scoped to
    # only the telemetry step + OIDC permissions — not any pending fix changes
    # that may be stored in wf.raw_content.
    file_changes: list[tuple[str, str]] = []
    for wf in workflow_files:
        try:
            gh_file = gh_repo.get_contents(wf.path, ref=branch)
            live_content = gh_file.decoded_content.decode("utf-8")  # type: ignore[union-attr]
        except GithubException:
            live_content = wf.raw_content
        new_content, modified = _inject_action_into_workflow(live_content)
        if modified:
            file_changes.append((wf.path, new_content))

    badge_added = False
    try:
        readme_file = gh_repo.get_readme(ref=branch)
        readme_content = readme_file.decoded_content.decode("utf-8")
        owner, name = repo.full_name.split("/", 1)
        badge_url = (
            f"{settings.BACKEND_HOST}{settings.API_V1_STR}"
            f"/badges/{owner}/{name}/{branch}.svg"
        )
        link_url = f"{settings.FRONTEND_HOST}/repositories/{repo_id}"
        badge_markdown = f"[![{app_name}]({badge_url})]({link_url})"

        if badge_url not in readme_content:
            new_readme = await _inject_badge_via_llm(
                readme_content, badge_markdown, repo
            )
            if (
                new_readme
                and badge_url in new_readme
                and _badge_only_added(readme_content, new_readme)
            ):
                file_changes.append((readme_file.path, new_readme))
            else:
                file_changes.append(
                    (
                        readme_file.path,
                        _insert_badge_simple(readme_content, badge_markdown),
                    )
                )
            badge_added = True
    except Exception:
        logger.exception("Badge injection failed for repo %s", repo.full_name)

    if not file_changes:
        raise HTTPException(
            status_code=409,
            detail=f"{app_name} action already present in all workflow files and badge already in README",
        )

    delivery = FixDeliveryService(github_client)
    fix_branch = "greensecops/integrate-action"

    pr_body_parts = [
        f"This PR adds the [{app_name} Telemetry]({settings.APP_URL}) action "
        "to your workflow files.\n\n"
        "Set the `GREENSECOPS_URL` repository variable to your GreenSecOps instance URL.",
    ]
    if badge_added:
        pr_body_parts.append(
            f"\n\n---\n\nA {app_name} grade badge has been added to your README."
        )

    result = await delivery.update_or_create_workflow_action_pr(
        installation_id=repo.installation_id,
        full_name=repo.full_name,
        base_branch=repo.default_branch or "main",
        fix_branch=fix_branch,
        file_changes=file_changes,
        pr_title=f"ci: add {app_name} telemetry action",
        pr_body="".join(pr_body_parts),
    )
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    if result.pr_url:
        events_pub.publish_event(
            ev.repository_action_pr_opened(
                str(repo.org_id), str(repo_id), result.pr_url
            )
        )
    return {"pr_url": result.pr_url or ""}
