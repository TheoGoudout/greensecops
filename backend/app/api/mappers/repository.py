from app.models import Repository, RepositoryPublic


def to_repo_public(
    repo: Repository, avg_score: float | None, grade: str | None
) -> RepositoryPublic:
    badge_sig: str | None = None
    if repo.is_private and "/" in repo.full_name:
        from app.services.badge_signing import repo_badge_message, sign_badge

        owner, name = repo.full_name.split("/", 1)
        badge_sig = sign_badge(repo_badge_message(owner, name, repo.default_branch))
    return RepositoryPublic(
        id=repo.id,
        org_id=repo.org_id,
        full_name=repo.full_name,
        enabled=repo.enabled,
        is_accessible=repo.is_accessible,
        is_external=repo.is_external,
        is_private=repo.is_private,
        default_branch=repo.default_branch,
        auto_fix_enabled=repo.auto_fix_enabled,
        badge_sig=badge_sig,
        created_at=repo.created_at,
        avg_score=avg_score,
        grade=grade,
    )
