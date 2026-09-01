"""Tests for the GitHub action SHA resolver."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from github.GithubException import GithubException, UnknownObjectException

from app.services.github.sha_resolver import (
    WELL_KNOWN_ACTIONS,
    _parse_action_refs,
    _resolve_ref_to_sha_sync,
    resolve_action_shas,
    resolve_and_pin_refs,
    resolve_pinned_ref,
)

# ─── helpers ─────────────────────────────────────────────────────────────────


class FakeRepo:
    """PyGitHub Repository stand-in backed by plain dicts.

    ``refs`` maps a ref path (e.g. ``tags/v4``) to a ``(sha, type)`` pair;
    ``annotated_tags`` maps an annotated tag object SHA to its commit SHA.
    """

    def __init__(
        self,
        refs: dict[str, tuple[str, str]] | None = None,
        latest_release: str | None = None,
        tags: list[str] | None = None,
        annotated_tags: dict[str, str] | None = None,
    ) -> None:
        self._refs = refs or {}
        self._latest_release = latest_release
        self._tags = tags or []
        self._annotated_tags = annotated_tags or {}

    def get_git_ref(self, ref_path: str) -> SimpleNamespace:
        if ref_path not in self._refs:
            raise UnknownObjectException(404, "Not Found", None)
        sha, obj_type = self._refs[ref_path]
        return SimpleNamespace(object=SimpleNamespace(sha=sha, type=obj_type))

    def get_git_tag(self, sha: str) -> SimpleNamespace:
        commit_sha = self._annotated_tags[sha]
        return SimpleNamespace(object=SimpleNamespace(sha=commit_sha, type="commit"))

    def get_latest_release(self) -> SimpleNamespace:
        if self._latest_release is None:
            raise GithubException(404, "Not Found", None)
        return SimpleNamespace(tag_name=self._latest_release)

    def get_tags(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name) for name in self._tags]


class FakeGithub:
    """PyGitHub client stand-in serving FakeRepo objects by full name."""

    def __init__(
        self,
        repos: dict[str, FakeRepo] | None = None,
        default_repo: FakeRepo | None = None,
    ) -> None:
        self._repos = repos or {}
        self._default_repo = default_repo
        self.get_repo_calls: list[str] = []

    def get_repo(self, full_name: str) -> FakeRepo:
        self.get_repo_calls.append(full_name)
        repo = self._repos.get(full_name, self._default_repo)
        if repo is None:
            raise UnknownObjectException(404, "Not Found", None)
        return repo


def _fake_cache(store: dict[str, str] | None = None) -> MagicMock:
    store = store if store is not None else {}
    cache = MagicMock()

    async def _get(key: str) -> str | None:
        return store.get(key)

    async def _setex(key: str, _ttl: int, value: str) -> None:
        store[key] = value

    cache.get = MagicMock(side_effect=_get)
    cache.setex = MagicMock(side_effect=_setex)

    async def _aclose() -> None:
        return None

    cache.aclose = MagicMock(side_effect=_aclose)

    @asynccontextmanager
    async def _noop_lock_cm():
        yield

    cache.lock = lambda *a, **kw: _noop_lock_cm()
    cache._store = store
    return cache


def _resolve(workflow: str, gh: FakeGithub, cache: MagicMock) -> dict[str, str]:
    with patch(
        "app.services.github.sha_resolver.aioredis.from_url",
        return_value=cache,
    ):
        return asyncio.run(resolve_action_shas(workflow, gh=gh))


# ─── _parse_action_refs ───────────────────────────────────────────────────────


def test_parse_action_refs_extracts_tag_ref() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    assert _parse_action_refs(workflow) == {("actions/checkout", "v4")}


def test_parse_action_refs_skips_already_pinned_sha() -> None:
    sha = "a" * 40
    assert _parse_action_refs(f"      - uses: actions/checkout@{sha}\n") == set()


def test_parse_action_refs_multiple_actions() -> None:
    workflow = (
        "      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n"
    )
    assert _parse_action_refs(workflow) == {
        ("actions/checkout", "v4"),
        ("actions/setup-python", "v5"),
    }


def test_parse_action_refs_deduplicates() -> None:
    workflow = "      - uses: actions/checkout@v4\n      - uses: actions/checkout@v4\n"
    assert _parse_action_refs(workflow) == {("actions/checkout", "v4")}


def test_parse_action_refs_empty_workflow() -> None:
    assert _parse_action_refs("") == set()


def test_parse_action_refs_no_uses() -> None:
    assert _parse_action_refs("name: CI\non: push\n") == set()


# ─── _resolve_ref_to_sha_sync ────────────────────────────────────────────────


def test_resolve_ref_to_sha_lightweight_tag() -> None:
    gh = FakeGithub(
        {"actions/checkout": FakeRepo(refs={"tags/v4": ("abc123", "commit")})}
    )
    assert _resolve_ref_to_sha_sync(gh, "actions/checkout", "v4") == "abc123"


def test_resolve_ref_to_sha_annotated_tag_dereferences() -> None:
    repo = FakeRepo(
        refs={"tags/v4": ("tag_sha", "tag")},
        annotated_tags={"tag_sha": "commit_sha"},
    )
    gh = FakeGithub({"actions/checkout": repo})
    assert _resolve_ref_to_sha_sync(gh, "actions/checkout", "v4") == "commit_sha"


def test_resolve_ref_to_sha_tag_missing_falls_back_to_branch() -> None:
    gh = FakeGithub(
        {"actions/checkout": FakeRepo(refs={"heads/main": ("branch_sha", "commit")})}
    )
    assert _resolve_ref_to_sha_sync(gh, "actions/checkout", "main") == "branch_sha"


def test_resolve_ref_to_sha_unresolvable_ref_returns_none() -> None:
    gh = FakeGithub({"actions/checkout": FakeRepo()})
    assert _resolve_ref_to_sha_sync(gh, "actions/checkout", "v4") is None


def test_resolve_ref_to_sha_unknown_repo_returns_none() -> None:
    gh = FakeGithub()
    assert _resolve_ref_to_sha_sync(gh, "actions/checkout", "v4") is None


def test_resolve_ref_to_sha_unexpected_exception_returns_none() -> None:
    repo = MagicMock()
    repo.get_git_ref.side_effect = Exception("network error")
    gh = FakeGithub({"actions/checkout": repo})
    assert _resolve_ref_to_sha_sync(gh, "actions/checkout", "v4") is None


# ─── resolve_action_shas ─────────────────────────────────────────────────────


def test_resolve_action_shas_resolves_referenced_action() -> None:
    gh = FakeGithub(default_repo=FakeRepo(refs={"tags/v4": ("resolved_sha", "commit")}))
    result = _resolve("      - uses: actions/checkout@v4\n", gh, _fake_cache())
    assert result["actions/checkout@v4"] == "resolved_sha"


def test_resolve_action_shas_includes_latest_versions_of_well_known_actions() -> None:
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={"tags/v9": ("latest_sha", "commit")}, latest_release="v9"
        )
    )
    result = _resolve("", gh, _fake_cache())
    for repo in WELL_KNOWN_ACTIONS:
        assert result[f"{repo}@v9"] == "latest_sha"


def test_resolve_action_shas_latest_version_falls_back_to_tags() -> None:
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={"tags/v7.1.2": ("tag_sha", "commit")}, tags=["v7.1.2"]
        )
    )
    result = _resolve("", gh, _fake_cache())
    assert result["actions/checkout@v7.1.2"] == "tag_sha"


def test_resolve_action_shas_skips_unresolvable_action() -> None:
    workflow = "      - uses: someorg/private-action@v1\n"
    result = _resolve(workflow, FakeGithub(), _fake_cache())
    assert result == {}


def test_resolve_action_shas_uses_cached_values() -> None:
    workflow = "      - uses: actions/checkout@v4\n"
    store = {"action_sha:actions/checkout@v4": "cached_sha"}
    for repo in set(WELL_KNOWN_ACTIONS) - {"actions/checkout"}:
        store.setdefault(f"action_version:latest:{repo}", "v9")
        store.setdefault(f"action_sha:{repo}@v9", "cached_latest_sha")

    gh = FakeGithub()  # any API call would raise → sha missing
    result = _resolve(workflow, gh, _fake_cache(store))

    assert result["actions/checkout@v4"] == "cached_sha"
    assert "actions/checkout@v9" not in result
    assert gh.get_repo_calls == []


def test_resolve_action_shas_does_not_bump_already_referenced_action() -> None:
    """An action already pinned to an older tag keeps that exact tag — no

    'latest' lookup or injection happens for it, even though it's in
    WELL_KNOWN_ACTIONS and a newer release exists upstream.
    """
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={"tags/v3": ("old_sha", "commit")},
            latest_release="v9",
        )
    )
    result = _resolve("      - uses: actions/checkout@v3\n", gh, _fake_cache())
    assert result == {"actions/checkout@v3": "old_sha"}
    assert "actions/checkout@v9" not in result


def test_resolve_action_shas_populates_cache() -> None:
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={
                "tags/v4": ("fresh_sha", "commit"),
                "tags/v9": ("fresh_sha", "commit"),
            },
            latest_release="v9",
        )
    )
    cache = _fake_cache()
    _resolve("      - uses: actions/checkout@v4\n", gh, cache)
    assert cache._store["action_sha:actions/checkout@v4"] == "fresh_sha"
    assert "action_version:latest:actions/checkout" not in cache._store


def test_resolve_action_shas_survives_redis_failure() -> None:
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={
                "tags/v4": ("resolved_sha", "commit"),
                "tags/v9": ("resolved_sha", "commit"),
            },
            latest_release="v9",
        )
    )
    with patch(
        "app.services.github.sha_resolver.aioredis.from_url",
        side_effect=RuntimeError("redis down"),
    ):
        result = asyncio.run(
            resolve_action_shas("      - uses: actions/checkout@v4\n", gh=gh)
        )
    assert result["actions/checkout@v4"] == "resolved_sha"


def test_resolve_action_shas_uses_provided_gh_instance() -> None:
    """Provided gh is used as-is; unauthenticated Github() is never instantiated."""
    provided_gh = FakeGithub(
        default_repo=FakeRepo(
            refs={"tags/v4": ("auth_sha", "commit")}, latest_release="v4"
        )
    )
    cache = _fake_cache()
    with (
        patch("app.services.github.sha_resolver.Github") as mock_gh_cls,
        patch("app.services.github.sha_resolver.aioredis.from_url", return_value=cache),
    ):
        result = asyncio.run(
            resolve_action_shas("      - uses: actions/checkout@v4\n", gh=provided_gh)
        )
    mock_gh_cls.assert_not_called()
    assert result["actions/checkout@v4"] == "auth_sha"


# ─── resolve_and_pin_refs ────────────────────────────────────────────────────


def _pin(content: str, gh: FakeGithub, cache: MagicMock) -> str:
    with patch(
        "app.services.github.sha_resolver.aioredis.from_url",
        return_value=cache,
    ):
        return asyncio.run(resolve_and_pin_refs(content, gh=gh))


def test_resolve_and_pin_refs_pins_new_unpinned_action() -> None:
    # A third-party action the LLM added — not in WELL_KNOWN_ACTIONS, not
    # already in the workflow — must still get pinned deterministically.
    workflow = "      - uses: nick-fields/retry@v2\n"
    gh = FakeGithub(default_repo=FakeRepo(refs={"tags/v2": ("retry_sha", "commit")}))
    result = _pin(workflow, gh, _fake_cache())
    assert "uses: nick-fields/retry@retry_sha # v2\n" in result


def test_resolve_and_pin_refs_leaves_unresolvable_ref_untouched() -> None:
    workflow = "      - uses: someorg/private-action@v1\n"
    result = _pin(workflow, FakeGithub(), _fake_cache())
    assert result == workflow


def test_resolve_and_pin_refs_leaves_already_pinned_sha_untouched() -> None:
    sha = "a" * 40
    workflow = f"      - uses: actions/checkout@{sha}  # v4\n"
    result = _pin(workflow, FakeGithub(), _fake_cache())
    assert result == workflow


def test_resolve_and_pin_refs_no_refs_returns_content_unchanged() -> None:
    content = "name: CI\non: push\n"
    result = _pin(content, FakeGithub(), _fake_cache())
    assert result == content


def test_resolve_and_pin_refs_pins_multiple_refs() -> None:
    workflow = "      - uses: nick-fields/retry@v2\n      - uses: actions/checkout@v4\n"
    gh = FakeGithub(
        repos={
            "nick-fields/retry": FakeRepo(refs={"tags/v2": ("retry_sha", "commit")}),
            "actions/checkout": FakeRepo(refs={"tags/v4": ("checkout_sha", "commit")}),
        }
    )
    result = _pin(workflow, gh, _fake_cache())
    assert "uses: nick-fields/retry@retry_sha # v2" in result
    assert "uses: actions/checkout@checkout_sha # v4" in result


# ─── resolve_pinned_ref ──────────────────────────────────────────────────────


def _resolve_single(ref: str, gh: FakeGithub, cache: MagicMock) -> str:
    with patch(
        "app.services.github.sha_resolver.aioredis.from_url",
        return_value=cache,
    ):
        return asyncio.run(resolve_pinned_ref(ref, gh=gh))


def test_resolve_pinned_ref_resolves_tag_to_sha() -> None:
    gh = FakeGithub(default_repo=FakeRepo(refs={"tags/v1": ("action_sha", "commit")}))
    result = _resolve_single("greensecops/telemetry@v1", gh, _fake_cache())
    assert result == "greensecops/telemetry@action_sha # v1"


def test_resolve_pinned_ref_leaves_as_is_when_unresolvable() -> None:
    result = _resolve_single("greensecops/telemetry@v1", FakeGithub(), _fake_cache())
    assert result == "greensecops/telemetry@v1"


def test_resolve_pinned_ref_leaves_already_pinned_sha_as_is() -> None:
    sha = "b" * 40
    ref = f"greensecops/greensecops-action@{sha}"
    result = _resolve_single(ref, FakeGithub(), _fake_cache())
    assert result == ref


def test_resolve_pinned_ref_leaves_malformed_ref_as_is() -> None:
    result = _resolve_single("not-a-valid-ref", FakeGithub(), _fake_cache())
    assert result == "not-a-valid-ref"


def test_resolve_pinned_ref_does_not_look_up_a_version_it_did_not_need() -> None:
    """The configured tag resolving is the end of it — no release lookup."""
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={"tags/v1": ("action_sha", "commit")}, latest_release="v1.4.0"
        )
    )
    result = _resolve_single("greensecops/telemetry@v1", gh, _fake_cache())
    assert result == "greensecops/telemetry@action_sha # v1"
    # One repo lookup: the tag. A second would mean the fallback ran anyway.
    assert gh.get_repo_calls == ["greensecops/telemetry"]


def test_resolve_pinned_ref_falls_back_to_the_latest_release() -> None:
    """A floating major tag that was never cut still yields a real pin.

    ``GITHUB_ACTION_REF`` defaults to ``…@v1``, which exists only once a v1
    release has been published. Before, this returned the ref unpinned and the
    generated workflow tripped the product's own ``unpinned_actions`` rule.
    """
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={"tags/v1.4.0": ("release_sha", "commit")},
            latest_release="v1.4.0",
        )
    )
    result = _resolve_single("greensecops/telemetry@v1", gh, _fake_cache())
    # The comment names the version actually pinned, not the one asked for.
    assert result == "greensecops/telemetry@release_sha # v1.4.0"


def test_resolve_pinned_ref_falls_back_to_the_newest_tag_without_a_release() -> None:
    gh = FakeGithub(
        default_repo=FakeRepo(
            refs={"tags/v0.2.0": ("tag_sha", "commit")}, tags=["v0.2.0", "v0.1.0"]
        )
    )
    result = _resolve_single("greensecops/telemetry@v1", gh, _fake_cache())
    assert result == "greensecops/telemetry@tag_sha # v0.2.0"


def test_resolve_pinned_ref_leaves_as_is_when_the_repo_has_no_versions() -> None:
    """No tag, no release, nothing to pin to — never invent a SHA."""
    gh = FakeGithub(default_repo=FakeRepo())
    result = _resolve_single("greensecops/telemetry@v1", gh, _fake_cache())
    assert result == "greensecops/telemetry@v1"


def test_resolve_pinned_ref_leaves_as_is_when_the_latest_version_is_the_asked_tag() -> (
    None
):
    """The release says ``v1`` too, and ``tags/v1`` already failed to resolve.

    Re-asking for the same ref would be a wasted API call answering the same
    way, so the ref is left alone rather than looked up twice.
    """
    gh = FakeGithub(default_repo=FakeRepo(latest_release="v1"))
    result = _resolve_single("greensecops/telemetry@v1", gh, _fake_cache())
    assert result == "greensecops/telemetry@v1"


def test_resolve_action_shas_acquires_lock_on_cache_miss() -> None:
    """Redis lock is acquired on a cache miss to prevent concurrent duplicate fetches."""
    lock_keys: list[str] = []

    @asynccontextmanager
    async def _tracking_lock(key: str, **kwargs):
        lock_keys.append(key)
        yield

    gh = FakeGithub(
        default_repo=FakeRepo(refs={"tags/v4": ("sha", "commit")}, latest_release="v4")
    )
    cache = _fake_cache()
    cache.lock = _tracking_lock

    with patch(
        "app.services.github.sha_resolver.aioredis.from_url", return_value=cache
    ):
        asyncio.run(resolve_action_shas("      - uses: actions/checkout@v4\n", gh=gh))

    assert any("action_sha:actions/checkout@v4" in k for k in lock_keys)
