from sqlmodel import Session, select

from app.models import (
    AnsibleFix,
    AnsibleProject,
    FixStatus,
    LLMProvider,
    PullRequest,
    PullRequestState,
)
from app.services.workflow_fixes import delete_orphaned_closed_prs
from tests.fixtures.factories import make_org, make_repo


def test_delete_orphaned_closed_prs_keeps_records_any_engine_references(
    db: Session,
) -> None:
    """A closed PR record an Ansible fix still points at must survive.

    Deleting it would clear that fix's ``pr_id`` through ON DELETE SET NULL.
    The check used to list the engines' fix tables by hand and had missed
    Ansible's.
    """
    repo = make_repo(db, make_org(db))
    project = AnsibleProject(repo_id=repo.id, root_path="")
    referenced = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/ansible",
        pr_state=PullRequestState.closed,
    )
    orphan = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/orphan",
        pr_state=PullRequestState.closed,
    )
    db.add_all([project, referenced, orphan])
    db.flush()
    db.add(
        AnsibleFix(
            ansible_project_id=project.id,
            file_path="site.yml",
            pr_id=referenced.id,
            llm_provider=LLMProvider.openai,
            llm_model="gpt-4o-mini",
            status=FixStatus.delivered,
        )
    )
    db.commit()

    delete_orphaned_closed_prs(db, repo.id)
    db.commit()

    remaining = set(
        db.exec(select(PullRequest.pr_branch).where(PullRequest.repo_id == repo.id))
    )
    assert remaining == {"greensecops/ansible"}
