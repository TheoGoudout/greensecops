"""Tests for the gates a rewrite passes before it is stored.

``_vet_rewrite`` is the shared chain for the Terraform, Docker and Ansible fix
flows: the rewrite must still parse as what it claims to be, must keep the
comments the file already carried, and must not violate a rule the original did
not. Each gate exists because a rewrite without it reached a real branch.
"""

from dataclasses import dataclass

from app.services.file_fix_generation import (
    MISSING_CONTENT_ERROR,
    _introduced_violations_error,
    _vet_rewrite,
)


@dataclass
class FakeFile:
    path: str
    content: str


_ORIGINAL = "services:\n  # localhost only.\n  db:\n    image: postgres:18\n"
_PATCHED = "services:\n  # localhost only.\n  db:\n    image: postgres:18\n    read_only: true\n"
_FETCHED = [FakeFile(path="compose.yml", content=_ORIGINAL)]


def _ok(_path: str, _original: str, _patched: str) -> str | None:
    return None


def _response(content: str) -> str:
    return f"<full_content>\n{content}</full_content>\n<unfixed>\n</unfixed>"


def test_a_clean_rewrite_passes_every_gate() -> None:
    content, error = _vet_rewrite(
        _response(_PATCHED), _ORIGINAL, "compose.yml", _FETCHED, _ok, None
    )
    assert error is None
    assert content == _PATCHED


def test_a_response_without_content_is_rejected() -> None:
    content, error = _vet_rewrite(
        "no envelope here", _ORIGINAL, "compose.yml", _FETCHED, _ok, None
    )
    assert content is None
    assert error == MISSING_CONTENT_ERROR


def test_the_engines_own_parse_gate_runs_first() -> None:
    def _rejects(_path: str, _original: str, _patched: str) -> str | None:
        return "LLM returned invalid Compose YAML"

    content, error = _vet_rewrite(
        _response(_PATCHED), _ORIGINAL, "compose.yml", _FETCHED, _rejects, None
    )
    assert content is None
    assert error == "LLM returned invalid Compose YAML"


def test_a_rewrite_that_drops_a_comment_is_rejected() -> None:
    stripped = _PATCHED.replace("  # localhost only.\n", "")
    content, error = _vet_rewrite(
        _response(stripped), _ORIGINAL, "compose.yml", _FETCHED, _ok, None
    )
    assert content is None
    assert error is not None
    assert "localhost only." in error


# ─── the re-scan ─────────────────────────────────────────────────────────────
#
# A rewrite is supposed to remove findings. One that trades a finding for a
# different one has not fixed the file, it has moved the problem — and the PR
# body would claim the trade as a win.


def test_a_rewrite_that_introduces_a_violation_is_rejected() -> None:
    def _rescan(files: list[tuple[str, str]]) -> set[str]:
        content = dict(files)["compose.yml"]
        return {"compose_service_unbounded"} | (
            {"compose_override_disables_read_only"} if "read_only" in content else set()
        )

    content, error = _vet_rewrite(
        _response(_PATCHED), _ORIGINAL, "compose.yml", _FETCHED, _ok, _rescan
    )
    assert content is None
    assert error is not None
    assert "compose_override_disables_read_only" in error
    # The rule the original already broke is not the rewrite's fault.
    assert "compose_service_unbounded" not in error


def test_a_rewrite_that_only_removes_violations_passes() -> None:
    def _rescan(files: list[tuple[str, str]]) -> set[str]:
        content = dict(files)["compose.yml"]
        return set() if "read_only" in content else {"compose_service_not_hardened"}

    content, error = _vet_rewrite(
        _response(_PATCHED), _ORIGINAL, "compose.yml", _FETCHED, _ok, _rescan
    )
    assert error is None
    assert content == _PATCHED


def test_the_rescan_evaluates_the_whole_target_not_one_file() -> None:
    """These engines fold every file into one document so a rule can correlate a
    Compose service with the Dockerfile it builds."""
    seen: list[list[tuple[str, str]]] = []

    def _rescan(files: list[tuple[str, str]]) -> set[str]:
        seen.append(files)
        return set()

    fetched = [
        FakeFile(path="compose.yml", content=_ORIGINAL),
        FakeFile(path="Dockerfile", content="FROM python:3.12\n"),
    ]
    _introduced_violations_error(_rescan, fetched, "compose.yml", _PATCHED)

    after, before = seen
    assert dict(after) == {"compose.yml": _PATCHED, "Dockerfile": "FROM python:3.12\n"}
    assert dict(before) == {
        "compose.yml": _ORIGINAL,
        "Dockerfile": "FROM python:3.12\n",
    }


def test_a_rescan_that_cannot_run_is_not_evidence_against_the_rewrite() -> None:
    """The parse gate has already had its say; a broken evaluator must not fail
    every fix the engine generates."""

    def _explodes(_files: list[tuple[str, str]]) -> set[str]:
        raise RuntimeError("no OPA here")

    assert (
        _introduced_violations_error(_explodes, _FETCHED, "compose.yml", _PATCHED)
        is None
    )
