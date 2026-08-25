"""Tests for the symbolic-ref half of ``services/github/action_metadata``.

The module's governing invariant is that an unanswered question must never
become a finding, so most of what is worth asserting here is what the collector
reports when GitHub does *not* answer.
"""

from typing import Any

from github.GithubException import GithubException, UnknownObjectException

from app.services.github.action_metadata import (
    ActionMetadata,
    _describe_sync,
    _symbolic_ref_kinds,
    parse_uses,
)


class _Repo:
    """A PyGithub repo stub answering only what these tests exercise."""

    def __init__(
        self,
        *,
        branches: set[str] | None = None,
        tags: set[str] | None = None,
        archived: bool = False,
        branch_error: Exception | None = None,
        tag_error: Exception | None = None,
    ) -> None:
        self._branches = branches or set()
        self._tags = tags or set()
        self.archived = archived
        self.default_branch = "main"
        self._branch_error = branch_error
        self._tag_error = tag_error

    def get_branch(self, ref: str) -> Any:
        if self._branch_error is not None:
            raise self._branch_error
        if ref not in self._branches:
            raise UnknownObjectException(404, None, None)
        return object()

    def get_git_ref(self, ref: str) -> Any:
        if self._tag_error is not None:
            raise self._tag_error
        if ref.removeprefix("tags/") not in self._tags:
            raise UnknownObjectException(404, None, None)
        return object()


def test_reports_both_kinds_when_a_name_is_branch_and_tag() -> None:
    repo = _Repo(branches={"v1"}, tags={"v1"})
    assert _symbolic_ref_kinds(repo, "v1") == ["branch", "tag"]


def test_reports_tag_only() -> None:
    repo = _Repo(branches=set(), tags={"v1"})
    assert _symbolic_ref_kinds(repo, "v1") == ["tag"]


def test_reports_branch_only() -> None:
    repo = _Repo(branches={"main"}, tags=set())
    assert _symbolic_ref_kinds(repo, "main") == ["branch"]


def test_reports_nothing_when_the_name_exists_as_neither() -> None:
    assert _symbolic_ref_kinds(_Repo(), "nope") == []


def test_a_missing_ref_is_not_an_error() -> None:
    # 404 from either lookup means "no ref of that kind", which is an answer.
    repo = _Repo(
        branches={"v1"}, tags=set(), tag_error=GithubException(404, None, None)
    )
    assert _symbolic_ref_kinds(repo, "v1") == ["branch"]


def test_an_unexpected_failure_yields_no_answer_at_all() -> None:
    # Not ["branch"]: a partial answer would let `ref_confusion` conclude
    # "unambiguous" from a lookup that never completed. Empty is silence.
    repo = _Repo(branches={"v1"}, tags={"v1"}, tag_error=RuntimeError("boom"))
    assert _symbolic_ref_kinds(repo, "v1") == []


def test_describe_populates_kinds_for_a_symbolic_ref() -> None:
    class _Gh:
        def get_repo(self, name: str) -> Any:
            return _Repo(branches={"v1"}, tags={"v1"})

    meta = _describe_sync(_Gh(), "example/action", "v1")
    assert meta.lookup == "ok"
    assert meta.ref_kind == "symbolic"
    assert meta.symbolic_ref_kinds == ["branch", "tag"]


def test_describe_does_not_ask_the_question_for_a_sha_pin() -> None:
    sha = "11bd71901bbe5b1630ceea73d27597364c9af683"

    class _ShaRepo(_Repo):
        def get_commit(self, ref: str) -> Any:
            raise UnknownObjectException(404, None, None)

    class _Gh:
        def get_repo(self, name: str) -> Any:
            return _ShaRepo()

    meta = _describe_sync(_Gh(), "example/action", sha)
    assert meta.ref_kind == "sha"
    assert meta.symbolic_ref_kinds == []


def test_default_metadata_carries_no_kinds() -> None:
    assert ActionMetadata(lookup="error", ref_kind="sha").symbolic_ref_kinds == []


def test_parse_uses_still_skips_local_and_docker_refs() -> None:
    assert parse_uses("./.github/actions/setup") is None
    assert parse_uses("docker://alpine:3.20") is None
    assert parse_uses("actions/checkout@v4") == ("actions/checkout", "v4")
