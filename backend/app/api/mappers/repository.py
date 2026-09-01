from app.models import Engine, RepoEngineGrade, Repository, RepositoryPublic
from app.services.badge_signing import repo_badge_message, sign_badge


def to_repo_public(
    repo: Repository,
    avg_score: float | None,
    grade: str | None,
    engine_grades: dict[Engine, tuple[float, str]] | None = None,
) -> RepositoryPublic:
    """Shape a repository for the API.

    ``engine_grades`` is optional so a caller that has no reason to aggregate
    five engines — a toggle returning the row it just wrote — does not pay for
    the query. An absent map renders as no per-engine grades, which is what a
    page shows as "—".
    """
    badge_sig: str | None = None
    if repo.is_private and "/" in repo.full_name:
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
        engine_grades=[
            RepoEngineGrade(engine=engine, score=score, grade=letter)
            for engine, (score, letter) in sorted(
                (engine_grades or {}).items(), key=lambda item: item[0].value
            )
        ],
    )
