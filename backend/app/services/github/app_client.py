import asyncio
import base64
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis
from github import Auth, Github, GithubIntegration
from github.GithubException import GithubException
from github.Repository import Repository as GithubRepository

from app.core.config import settings
from app.models.enums import CIStatus, PullRequestState, ReviewDecision

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models import Repository

_PR_URL_RE = re.compile(
    r"https://github\.com/(?P<full_name>[^/]+/[^/]+)/pull/(?P<number>\d+)"
)


def parse_pr_url(pr_url: str) -> tuple[str, int] | None:
    m = _PR_URL_RE.match(pr_url)
    if m:
        return m.group("full_name"), int(m.group("number"))
    return None


@dataclass
class WorkflowFileContent:
    path: str
    content: str
    content_hash: str
    sha: str


@dataclass
class TerraformFileContent:
    path: str
    content: str
    content_hash: str
    sha: str


@dataclass
class DockerFileContent:
    path: str
    content: str
    content_hash: str
    sha: str


# A pathological repo (a huge module tree, or a committed .terraform/ provider
# cache) must not turn one scan into thousands of GitHub API calls.
_TERRAFORM_MAX_FILES = 200
_TERRAFORM_MAX_DEPTH = 12
_TERRAFORM_EXTENSIONS = (".tf", ".tf.json")
# .terraform/ is Terraform's own local provider/module cache — huge, binary,
# never meant to be committed, and if it is, never worth scanning.
_TERRAFORM_SKIP_DIRS = {".terraform", ".git"}

# Same guard rails for Docker. Vendored dependency trees routinely contain
# hundreds of third-party Dockerfiles that are not this repository's to fix,
# and walking them would blow the file budget before reaching the real ones.
_DOCKER_MAX_FILES = 200
_DOCKER_MAX_DEPTH = 12
_DOCKER_SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".venv"}


@dataclass
class InstallationRepo:
    github_repo_id: int
    full_name: str
    default_branch: str
    private: bool = False


@dataclass
class PRSnapshot:
    """A poll's normalized view of a pull request.

    Gathers, in one fetch, everything the poller needs to drive the same
    handlers a webhook would: lifecycle state plus the CI/review/head-commit
    attributes. The external-repo analogue of the several ``pull_request`` /
    ``check_suite`` / ``pull_request_review`` webhook payloads.
    """

    state: PullRequestState
    merged: bool
    draft: bool
    head_sha: str
    mergeable_state: str | None
    ci_status: CIStatus
    # ``None`` means "no decisive review" — the caller leaves the current value.
    review_decision: ReviewDecision | None


@dataclass
class UserInstallation:
    installation_id: int
    account_id: int
    account_login: str
    account_type: str  # "User" | "Organization"


class GitHubAppClient:
    """GitHub App client with PyGitHub and Redis-cached installation tokens."""

    _TOKEN_TTL = 55 * 60  # 55 minutes (tokens last 60 min)
    _APP_LOGIN_TTL = 24 * 60 * 60  # 24 hours (the app slug is stable)
    # Forks are created asynchronously; poll until the fork's git data is ready.
    _FORK_POLL_ATTEMPTS = 30
    _FORK_POLL_INTERVAL = 2  # seconds (≈60s max)

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    def _decode_private_key(self) -> str:
        key = settings.GITHUB_APP_PRIVATE_KEY or ""
        key = key.strip()
        # Support base64-encoded keys (useful for env vars without newline issues)
        if not key.startswith("-----"):
            try:
                key = base64.b64decode(key).decode()
            except Exception:
                pass
        return key

    def _get_integration(self) -> GithubIntegration:
        return GithubIntegration(
            # GITHUB_APP_ID is Optional in Settings but required for App auth.
            auth=Auth.AppAuth(settings.GITHUB_APP_ID, self._decode_private_key())  # type: ignore[arg-type]
        )

    async def get_installation_token(self, installation_id: int) -> str:
        cache_key = f"gh:install_token:{installation_id}"
        cached = await self._redis.get(cache_key)
        if cached:
            return str(cached.decode())

        def _exchange() -> str:
            return str(self._get_integration().get_access_token(installation_id).token)

        token = await asyncio.to_thread(_exchange)
        await self._redis.setex(cache_key, self._TOKEN_TTL, token)
        return token

    async def github_for_installation(
        self, installation_id: int | None
    ) -> Github | None:
        """A PyGithub client authenticated as this installation, or None.

        Two callers now need the same token-to-client dance — fix generation,
        for resolving action SHAs into the prompt, and static analysis, for the
        action metadata the pin-integrity rules read. It was inlined in the
        first; a second copy would be a second place for the fallback behaviour
        to drift.

        None means "carry on unauthenticated or not at all", and the choice is
        the caller's: the anonymous budget is 60 requests an hour, which is
        enough to pin a handful of refs and not enough to describe every action
        in a repository.
        """
        if installation_id is None:
            return None
        try:
            token = await self.get_installation_token(installation_id)
            return Github(auth=Auth.Token(token))
        except Exception:
            logger.warning(
                "Failed to build an authenticated GitHub client for installation %s",
                installation_id,
                exc_info=True,
            )
            return None

    async def get_app_bot_login(self) -> str:
        """Return the authenticated App's own bot login (``<slug>[bot]``).

        Commits made with an installation token are authored by this login, so it
        is the identity to trust when deciding whether a branch carries only the
        bot's own work. Deriving it from the App itself (rather than a separately
        configured handle) keeps the check correct across environments whose app
        slugs differ, e.g. ``greensecops`` vs ``greensecops-staging``.

        The slug is stable, so the result is cached in Redis. Falls back to
        ``settings.GITHUB_BOT_HANDLE`` if the lookup fails, so behavior is never
        worse than the previous config-only comparison.
        """
        cache_key = "gh:app_bot_login"
        cached = await self._redis.get(cache_key)
        if cached:
            return str(cached.decode())

        def _fetch_slug() -> str | None:
            slug: str | None = self._get_integration().get_app().slug
            return slug

        try:
            slug = await asyncio.to_thread(_fetch_slug)
        except Exception:
            slug = None

        bot_login = f"{slug}[bot]" if slug else settings.GITHUB_BOT_HANDLE
        if slug:
            await self._redis.setex(cache_key, self._APP_LOGIN_TTL, bot_login)
        return bot_login

    # ─── Bot account (external outreach PRs) ─────────────────────────────────

    def get_bot_github(self) -> Github:
        """Return a PyGitHub client authenticated as the outreach bot account.

        Raises if ``GITHUB_BOT_TOKEN`` is unset, so callers can surface a clear
        "no bot credential" state instead of an opaque auth failure.
        """
        if not settings.GITHUB_BOT_TOKEN:
            raise RuntimeError("GITHUB_BOT_TOKEN is not configured")
        return Github(auth=Auth.Token(settings.GITHUB_BOT_TOKEN))

    async def get_bot_login(self) -> str:
        """Return the bot account login (the owner of outreach forks).

        Uses ``GITHUB_BOT_LOGIN`` when set, otherwise derives it from the token
        and caches it in Redis (the login is stable).
        """
        if settings.GITHUB_BOT_LOGIN:
            return settings.GITHUB_BOT_LOGIN
        cache_key = "gh:bot_login"
        cached = await self._redis.get(cache_key)
        if cached:
            return str(cached.decode())

        def _fetch_login() -> str:
            return self.get_bot_github().get_user().login

        login = await asyncio.to_thread(_fetch_login)
        await self._redis.setex(cache_key, self._APP_LOGIN_TTL, login)
        return login

    def ensure_fork(self, bot: Github, full_name: str) -> GithubRepository:
        """Return the bot's fork of ``full_name``, creating it if needed.

        Forks are created asynchronously by GitHub, so after creating one this
        polls until its default branch resolves before returning it.
        """
        _, repo_name = full_name.split("/", 1)
        bot_user = bot.get_user()
        try:
            existing = bot_user.get_repo(repo_name)
            if (
                existing.fork
                and existing.parent
                and existing.parent.full_name.lower() == full_name.lower()
            ):
                return existing
        except GithubException:
            pass

        fork = bot.get_repo(full_name).create_fork()
        for _ in range(self._FORK_POLL_ATTEMPTS):
            try:
                fork.get_branch(fork.default_branch)
                return fork
            except GithubException:
                time.sleep(self._FORK_POLL_INTERVAL)
                fork = bot.get_repo(f"{bot_user.login}/{repo_name}")
        return fork

    async def get_pr_state_with_token(
        self, token: str, full_name: str, pr_number: int
    ) -> PullRequestState:
        def _fetch() -> PullRequestState:
            repo = Github(auth=Auth.Token(token)).get_repo(full_name)
            pr = repo.get_pull(pr_number)
            if pr.merged:
                return PullRequestState.merged
            return PullRequestState(pr.state)

        return await asyncio.to_thread(_fetch)

    async def get_pr_state(
        self, installation_id: int, full_name: str, pr_number: int
    ) -> PullRequestState:
        token = await self.get_installation_token(installation_id)
        return await self.get_pr_state_with_token(token, full_name, pr_number)

    async def get_pr_mergeable_state(
        self, installation_id: int, full_name: str, pr_number: int
    ) -> str | None:
        """Return GitHub's mergeable_state (e.g. ``clean``, ``dirty``) for a PR.

        GitHub sends no webhook when a base-branch push makes a PR conflicted,
        so this is polled on demand. ``None`` when GitHub hasn't computed it.
        """
        token = await self.get_installation_token(installation_id)

        def _fetch() -> str | None:
            repo = Github(auth=Auth.Token(token)).get_repo(full_name)
            return repo.get_pull(pr_number).mergeable_state

        return await asyncio.to_thread(_fetch)

    # ─── Polling snapshots (external-repo reconciliation) ────────────────────

    async def resolve_repo_token(self, repo: "Repository") -> str | None:
        """Return the credential to read a repo with, or ``None`` for public read.

        Mirrors the fix-delivery path: an installed repo uses its installation
        token; an external repo uses the configured bot token; a public external
        repo with no bot token is read unauthenticated (``None``).
        """
        if repo.installation_id:
            return await self.get_installation_token(repo.installation_id)
        if repo.is_external and settings.GITHUB_BOT_TOKEN:
            return settings.GITHUB_BOT_TOKEN
        return None

    async def get_default_branch_head(
        self, token: str | None, full_name: str
    ) -> tuple[str, str]:
        """Return ``(default_branch, head_sha)`` for ``full_name``.

        The polling analogue of a ``push`` webhook: a change in the head SHA
        since the last poll means new commits landed on the default branch.
        """

        def _fetch() -> tuple[str, str]:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            branch = repo.default_branch
            return branch, repo.get_branch(branch).commit.sha

        return await asyncio.to_thread(_fetch)

    async def get_pull_request_snapshot(
        self, token: str | None, full_name: str, pr_number: int
    ) -> PRSnapshot:
        """Fetch a PR's lifecycle + CI/review/head attributes in one call."""
        from app.services.github.event_handlers import review_state_to_decision

        def _fetch() -> PRSnapshot:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            pr = repo.get_pull(pr_number)
            head_sha = pr.head.sha if pr.head else ""

            # CI: aggregate the head commit's check-runs into a single CIStatus,
            # matching the webhook's check_suite semantics.
            ci_status = CIStatus.none
            if head_sha:
                runs = list(repo.get_commit(head_sha).get_check_runs())
                if not runs:
                    ci_status = CIStatus.none
                elif any(r.status != "completed" for r in runs):
                    ci_status = CIStatus.pending
                elif all(r.conclusion == "success" for r in runs):
                    ci_status = CIStatus.success
                elif any(
                    r.conclusion
                    in ("failure", "timed_out", "cancelled", "action_required")
                    for r in runs
                ):
                    ci_status = CIStatus.failure

            # Review decision: the most recent review carrying a decision, which
            # is exactly what the pull_request_review webhook records.
            decision: ReviewDecision | None = None
            for review in pr.get_reviews():
                mapped = review_state_to_decision(review.state or "")
                if mapped is not None:
                    decision = mapped

            state = PullRequestState.merged if pr.merged else PullRequestState(pr.state)
            return PRSnapshot(
                state=state,
                merged=bool(pr.merged),
                draft=bool(pr.draft),
                head_sha=head_sha,
                mergeable_state=pr.mergeable_state,
                ci_status=ci_status,
                review_decision=decision,
            )

        return await asyncio.to_thread(_fetch)

    async def list_pr_command_comments(
        self,
        token: str | None,
        full_name: str,
        pr_number: int,
        since: datetime | None,
    ) -> list[str]:
        """Return PR comment bodies created after ``since`` (issue comments).

        The polling analogue of the ``issue_comment`` webhook: lets the poller
        pick up ``/greensecops`` commands on an external repo's fix PR.
        """

        def _fetch() -> list[str]:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            issue = repo.get_issue(pr_number)
            comments = (
                issue.get_comments(since=since)
                if since is not None
                else issue.get_comments()
            )
            return [c.body for c in comments if c.body]

        return await asyncio.to_thread(_fetch)

    async def fetch_workflow_files(
        self, installation_id: int | None, full_name: str, ref: str | None = None
    ) -> list[WorkflowFileContent]:
        """Fetch workflow files at ``ref`` (branch or commit SHA).

        When ``ref`` is empty the repository's default branch is used, so an
        analysis triggered for a feature branch sees that branch's content.
        """
        if installation_id is not None:
            token: str | None = await self.get_installation_token(installation_id)
        else:
            token = None

        def _fetch() -> list[WorkflowFileContent]:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            try:
                if ref:
                    contents = repo.get_contents(".github/workflows", ref=ref)
                else:
                    contents = repo.get_contents(".github/workflows")
            except GithubException as exc:
                if exc.status == 404:
                    return []
                raise
            if not isinstance(contents, list):
                contents = [contents]
            results = []
            for cf in contents:
                if not (cf.name.endswith(".yml") or cf.name.endswith(".yaml")):
                    continue
                decoded = cf.decoded_content.decode("utf-8", errors="replace")
                results.append(
                    WorkflowFileContent(
                        path=cf.path,
                        content=decoded,
                        content_hash=hashlib.sha256(decoded.encode()).hexdigest(),
                        sha=cf.sha,
                    )
                )
            return results

        return await asyncio.to_thread(_fetch)

    async def fetch_terraform_files(
        self,
        installation_id: int | None,
        full_name: str,
        root_path: str,
        ref: str | None = None,
    ) -> list[TerraformFileContent]:
        """Recursively fetch ``.tf``/``.tf.json`` files under ``root_path`` at ``ref``.

        Unlike ``fetch_workflow_files`` (a single, non-recursive directory),
        Terraform roots can nest submodules arbitrarily deep, so this walks
        the tree — bounded by ``_TERRAFORM_MAX_FILES``/``_TERRAFORM_MAX_DEPTH``.
        Returns ``[]`` if ``root_path`` doesn't exist at ``ref``.
        """
        if installation_id is not None:
            token: str | None = await self.get_installation_token(installation_id)
        else:
            token = None

        def _fetch() -> list[TerraformFileContent]:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            results: list[TerraformFileContent] = []

            def _walk(path: str, depth: int) -> None:
                if depth > _TERRAFORM_MAX_DEPTH or len(results) >= _TERRAFORM_MAX_FILES:
                    return
                try:
                    contents = (
                        repo.get_contents(path, ref=ref)
                        if ref
                        else repo.get_contents(path)
                    )
                except GithubException as exc:
                    if exc.status == 404:
                        return
                    raise
                if not isinstance(contents, list):
                    contents = [contents]
                for cf in contents:
                    if len(results) >= _TERRAFORM_MAX_FILES:
                        return
                    if cf.type == "dir":
                        if cf.name in _TERRAFORM_SKIP_DIRS or cf.name.startswith("."):
                            continue
                        _walk(cf.path, depth + 1)
                    elif cf.name.endswith(_TERRAFORM_EXTENSIONS):
                        decoded = cf.decoded_content.decode("utf-8", errors="replace")
                        results.append(
                            TerraformFileContent(
                                path=cf.path,
                                content=decoded,
                                content_hash=hashlib.sha256(
                                    decoded.encode()
                                ).hexdigest(),
                                sha=cf.sha,
                            )
                        )

            _walk(root_path, 0)
            return results

        return await asyncio.to_thread(_fetch)

    async def fetch_docker_files(
        self,
        installation_id: int | None,
        full_name: str,
        root_path: str,
        ref: str | None = None,
    ) -> list[DockerFileContent]:
        """Recursively fetch Dockerfiles and Compose files under ``root_path``.

        Which filenames count is decided by
        ``services.docker.merge.classify_docker_file`` rather than a suffix
        tuple, so the fetcher and the scanner can never disagree about what a
        Docker file is — a mismatch would silently drop files from a scan.

        Returns ``[]`` if ``root_path`` doesn't exist at ``ref``.
        """
        from app.services.docker.merge import classify_docker_file

        if installation_id is not None:
            token: str | None = await self.get_installation_token(installation_id)
        else:
            token = None

        def _fetch() -> list[DockerFileContent]:
            gh = Github(auth=Auth.Token(token)) if token is not None else Github()
            repo = gh.get_repo(full_name)
            results: list[DockerFileContent] = []

            def _walk(path: str, depth: int) -> None:
                if depth > _DOCKER_MAX_DEPTH or len(results) >= _DOCKER_MAX_FILES:
                    return
                try:
                    contents = (
                        repo.get_contents(path, ref=ref)
                        if ref
                        else repo.get_contents(path)
                    )
                except GithubException as exc:
                    if exc.status == 404:
                        return
                    raise
                if not isinstance(contents, list):
                    contents = [contents]
                for cf in contents:
                    if len(results) >= _DOCKER_MAX_FILES:
                        return
                    if cf.type == "dir":
                        if cf.name in _DOCKER_SKIP_DIRS or cf.name.startswith("."):
                            continue
                        _walk(cf.path, depth + 1)
                    elif classify_docker_file(cf.name) is not None:
                        decoded = cf.decoded_content.decode("utf-8", errors="replace")
                        results.append(
                            DockerFileContent(
                                path=cf.path,
                                content=decoded,
                                content_hash=hashlib.sha256(
                                    decoded.encode()
                                ).hexdigest(),
                                sha=cf.sha,
                            )
                        )

            # A target rooted at "" is the repository root; PyGithub wants ""
            # for that, which is what an empty root_path already is.
            _walk(root_path, 0)
            return results

        return await asyncio.to_thread(_fetch)

    async def fetch_public_repo_info(self, full_name: str) -> InstallationRepo:
        """Fetch repo metadata via unauthenticated PyGitHub (public repos only)."""
        from github.GithubException import UnknownObjectException

        def _fetch() -> InstallationRepo:
            repo = Github().get_repo(full_name)
            return InstallationRepo(
                github_repo_id=repo.id,
                full_name=repo.full_name,
                default_branch=repo.default_branch or "main",
                private=bool(repo.private),
            )

        try:
            return await asyncio.to_thread(_fetch)
        except UnknownObjectException:
            raise ValueError(f"Repository '{full_name}' not found or is private")

    async def list_installation_repositories(
        self, installation_id: int
    ) -> list[InstallationRepo]:
        def _list() -> list[InstallationRepo]:
            installation = self._get_integration().get_app_installation(installation_id)
            return [
                InstallationRepo(
                    github_repo_id=repo.id,
                    full_name=repo.full_name,
                    default_branch=repo.default_branch or "main",
                    private=bool(repo.private),
                )
                for repo in installation.get_repos()
            ]

        return await asyncio.to_thread(_list)

    async def list_user_installations(
        self, user_access_token: str
    ) -> list[UserInstallation]:
        def _list() -> list[UserInstallation]:
            user = Github(auth=Auth.Token(user_access_token)).get_user()
            results = []
            for inst in user.get_installations():
                account = inst.account
                results.append(
                    UserInstallation(
                        installation_id=inst.id,
                        account_id=account.id,
                        account_login=account.login,
                        account_type=account.type,
                    )
                )
            return results

        return await asyncio.to_thread(_list)

    async def get_app_installation(self, installation_id: int) -> dict[str, Any]:
        def _get() -> dict[str, Any]:
            return (
                self._get_integration().get_app_installation(installation_id).raw_data
            )

        return await asyncio.to_thread(_get)

    async def get_oauth_user(self, access_token: str) -> dict[str, Any]:
        def _get() -> dict[str, Any]:
            user = Github(auth=Auth.Token(access_token)).get_user()
            return {
                "id": user.id,
                "login": user.login,
                "name": user.name,
                "email": user.email,
                "avatar_url": user.avatar_url,
            }

        return await asyncio.to_thread(_get)

    async def exchange_oauth_code(
        self,
        code: str,
        code_verifier: str | None = None,
        redirect_uri: str | None = None,
    ) -> str:
        def _exchange() -> str:
            # Optional in Settings but required for the OAuth flow.
            app = Github().get_oauth_application(
                settings.GITHUB_CLIENT_ID,  # type: ignore[arg-type]
                settings.GITHUB_CLIENT_SECRET,  # type: ignore[arg-type]
            )
            token = app.get_access_token(code, code_verifier)
            return token.token

        return await asyncio.to_thread(_exchange)
