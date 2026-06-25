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
    get_current_active_superuser,
    get_or_404,
)
from app.api.mappers import to_repo_public
from app.models import (
    Analysis,
    AnalysisStatus,
    ExternalRepositoryCreate,
    OrgMember,
    Repository,
    RepositoryPublic,
    User,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.services.scoring import score_to_grade

SuperuserDep = Annotated[User, Depends(get_current_active_superuser)]

_ACTION_USES_PREFIX = "greensecops/greensecops-action"


router = APIRouter(prefix="/repositories", tags=["repositories"])


def _user_org_ids(session: Session, user: User) -> set[uuid.UUID]:
    return set(
        session.exec(select(OrgMember.org_id).where(OrgMember.user_id == user.id)).all()
    )


def _get_repo_for_user(
    repo_id: uuid.UUID, session: Session, current_user: User
) -> Repository:
    repo = get_or_404(session, Repository, repo_id)
    if not current_user.is_superuser and repo.org_id not in _user_org_ids(
        session, current_user
    ):
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


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

    seen: set[uuid.UUID] = set()
    latest_per_file: list[Analysis] = []
    for a in analyses:
        if a.workflow_file_id not in seen:
            seen.add(a.workflow_file_id)
            latest_per_file.append(a)

    if not latest_per_file:
        return None, None, 0

    avg = sum(a.score for a in latest_per_file if a.score is not None) / len(  # type: ignore[arg-type]
        latest_per_file
    )
    return round(avg, 1), score_to_grade(avg), len(latest_per_file)


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


def _inject_action_into_workflow(raw_content: str) -> tuple[str, bool]:
    """Parse workflow YAML to find insertion points, then insert the action step as raw text.

    Uses ruamel.yaml only for parsing (to get line numbers and detect duplicates).
    Serialization is text-based so the PR diff contains only the inserted lines.
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

    # Collect (line_index, dash_column) for each job that needs the step inserted.
    insertions: list[tuple[int, int]] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            continue
        already_present = any(
            isinstance(s, dict)
            and str(s.get("uses", "")).startswith(_ACTION_USES_PREFIX)
            for s in steps
        )
        if already_present:
            continue
        try:
            first_step_line, first_step_val_col = steps.lc.data[0]
        except (AttributeError, KeyError, IndexError):
            continue
        # lc.data stores the column of the value (after "- "), so dash is 2 columns earlier.
        insertions.append((first_step_line, first_step_val_col - 2))

    if not insertions:
        return raw_content, False

    lines = raw_content.splitlines(keepends=True)
    # Process in reverse order so earlier line numbers stay valid.
    for line_idx, col in sorted(insertions, key=lambda x: x[0], reverse=True):
        indent = " " * col
        step_lines = (
            f"{indent}- name: GreenSecOps Telemetry\n"
            f"{indent}  uses: greensecops/greensecops-action@v1\n"
            f"{indent}  with:\n"
            f"{indent}    greensecops_url: ${{{{ vars.GREENSECOPS_URL }}}}\n"
        ).splitlines(keepends=True)
        lines[line_idx:line_idx] = step_lines

    return "".join(lines), True


_BADGE_MARKER = "<!-- greensecops-badge -->"


def _inject_badge_into_readme(
    raw_content: str, badge_url: str, link_url: str
) -> tuple[str, bool]:
    """Prepend a GreenSecOps badge to README content if not already present."""
    if _BADGE_MARKER in raw_content:
        return raw_content, False
    badge_line = (
        f"{_BADGE_MARKER}\n"
        f"[![GreenSecOps]({badge_url})]({link_url})\n\n"
    )
    return badge_line + raw_content, True


@router.post("/{repo_id}/integrate-action", status_code=202)
async def integrate_action(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    github_client: GitHubAppClientDep,
) -> dict[str, str]:
    from github import Auth, Github
    from github.GithubException import GithubException

    from app.core.config import settings
    from app.services.github.fix_delivery import FixDeliveryService

    repo = _get_repo_for_user(repo_id, session, current_user)

    workflow_files = repo.workflow_files
    if not workflow_files:
        raise HTTPException(
            status_code=404, detail="No workflow files found for this repository"
        )

    if repo.installation_id is None:
        raise HTTPException(
            status_code=400,
            detail="Repository has no GitHub App installation — ask the repo owner to install the GreenSecOps GitHub App first",
        )

    file_changes: list[tuple[str, str]] = []
    for wf in workflow_files:
        new_content, modified = _inject_action_into_workflow(wf.raw_content)
        if modified:
            file_changes.append((wf.path, new_content))

    badge_added = False
    try:
        token = await github_client.get_installation_token(repo.installation_id)
        gh_repo = Github(auth=Auth.Token(token)).get_repo(repo.full_name)
        branch = repo.default_branch or "main"
        try:
            readme_file = gh_repo.get_readme(ref=branch)
            readme_content = readme_file.decoded_content.decode("utf-8")
            owner, name = repo.full_name.split("/", 1)
            badge_url = (
                f"{settings.BACKEND_HOST}{settings.API_V1_STR}"
                f"/badges/{owner}/{name}/{branch}.svg"
            )
            link_url = f"{settings.FRONTEND_HOST}/repositories/{repo_id}"
            new_readme, badge_added = _inject_badge_into_readme(
                readme_content, badge_url, link_url
            )
            if badge_added:
                file_changes.append((readme_file.path, new_readme))
        except GithubException:
            pass
    except Exception:
        pass

    if not file_changes:
        raise HTTPException(
            status_code=409,
            detail="GreenSecOps action already present in all workflow files and badge already in README",
        )

    delivery = FixDeliveryService(github_client)
    fix_branch = "greensecops/integrate-action"

    pr_body_parts = [
        "This PR adds the [GreenSecOps Telemetry](https://greensecops.io) action "
        "to your workflow files.\n\n"
        "Set the `GREENSECOPS_URL` repository variable to your GreenSecOps instance URL.",
    ]
    if badge_added:
        pr_body_parts.append(
            "\n\n---\n\nA GreenSecOps grade badge has been added to your README."
        )

    result = await delivery.update_or_create_workflow_action_pr(
        installation_id=repo.installation_id,
        full_name=repo.full_name,
        base_branch=repo.default_branch or "main",
        fix_branch=fix_branch,
        file_changes=file_changes,
        pr_title="ci: add GreenSecOps telemetry action",
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
