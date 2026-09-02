"""The PR body and the no-op filter for the Terraform/Docker/Ansible delivery.

A finding the generator declined must not be listed as fixed. Claiming one is
worse than omitting it: the reviewer reads the table, sees the rule named, and
assumes the diff below addresses it.
"""

from types import SimpleNamespace

from app.services.engines import DOCKER_ENGINE
from app.services.file_fix_delivery import _resolves_something, build_pr_body


def _finding(
    slug: str,
    message: str,
    *,
    needs_manual_work: bool = False,
    note: str | None = None,
    resolved: bool = False,
) -> object:
    return SimpleNamespace(
        rule=SimpleNamespace(slug=slug),
        severity=SimpleNamespace(value="low"),
        message=message,
        resolved_at="2026-01-01" if resolved else None,
        needs_manual_work=needs_manual_work,
        manual_work_note=note,
    )


def _fix(file_path: str, findings: list[object]) -> object:
    return SimpleNamespace(file_path=file_path, findings=findings)


def test_a_fixed_finding_is_listed_under_its_file() -> None:
    body = build_pr_body(
        DOCKER_ENGINE,
        [_fix("compose.yml", [_finding("compose_service_unbounded", "no limit")])],
    )
    assert "### `compose.yml`" in body
    assert "**compose_service_unbounded** (low): no limit" in body
    assert "Needs manual work" not in body


def test_a_declined_finding_moves_to_its_own_section() -> None:
    body = build_pr_body(
        DOCKER_ENGINE,
        [
            _fix(
                "Dockerfile",
                [
                    _finding("missing_healthcheck", "no healthcheck"),
                    _finding(
                        "container_runs_as_root",
                        "runs as root",
                        needs_manual_work=True,
                        note="the file says this is deliberate",
                    ),
                ],
            )
        ],
    )
    fixed, manual = body.split("## Needs manual work")
    assert "missing_healthcheck" in fixed
    assert "container_runs_as_root" not in fixed
    assert "container_runs_as_root" in manual
    assert "the file says this is deliberate" in manual
    assert "1 finding was analysed but **not** changed" in manual


def test_an_already_resolved_finding_is_listed_nowhere() -> None:
    body = build_pr_body(
        DOCKER_ENGINE,
        [_fix("compose.yml", [_finding("gone", "already fixed", resolved=True)])],
    )
    assert "gone" not in body


# ─── the no-op filter ────────────────────────────────────────────────────────


def test_a_fix_that_resolves_something_is_deliverable() -> None:
    assert _resolves_something(
        _fix(
            "Dockerfile",
            [_finding("a", "x"), _finding("b", "y", needs_manual_work=True)],
        )
    )


def test_a_fix_that_declined_every_finding_is_withheld() -> None:
    """Whatever it returned is an edit no finding asked for."""
    assert not _resolves_something(
        _fix("Dockerfile", [_finding("a", "x", needs_manual_work=True)])
    )


def test_a_fix_with_no_open_findings_is_still_deliverable() -> None:
    """Findings relinked or swept is a different case from every one declined."""
    assert _resolves_something(_fix("Dockerfile", []))
    assert _resolves_something(_fix("Dockerfile", [_finding("a", "x", resolved=True)]))
