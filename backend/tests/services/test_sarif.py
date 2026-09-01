"""The SARIF mapping: what GitHub is told, and what it is not told.

Every assertion here is about a field GitHub actually reads. The format is
permissive enough that a wrong document uploads cleanly and simply shows
nothing, so the failure mode this guards against is silence rather than an
error.
"""

from __future__ import annotations

from app.models.enums import Category, Severity
from app.services.sarif import SarifFinding, build_sarif

TOOL = {
    "tool_name": "GreenSecOps (docker)",
    "tool_version": "1.2.3",
    "information_uri": "https://greensecops.com",
}


def _finding(**overrides: object) -> SarifFinding:
    defaults: dict[str, object] = {
        "rule_slug": "unpinned_base_image",
        "rule_title": "Base image is not pinned",
        "rule_description": "A floating tag can change under you.",
        "severity": Severity.high,
        "category": Category.security,
        "message": "FROM python:3.12-slim is not pinned to a digest",
        "file_path": "Dockerfile",
        "line_start": 3,
        "line_end": 3,
        "fingerprint": "abc123",
    }
    defaults.update(overrides)
    return SarifFinding(**defaults)  # type: ignore[arg-type]


def _run(document: dict) -> dict:
    return document["runs"][0]  # type: ignore[no-any-return]


def _results(document: dict) -> list[dict]:
    return _run(document)["results"]  # type: ignore[no-any-return]


def _rules(document: dict) -> list[dict]:
    return _run(document)["tool"]["driver"]["rules"]  # type: ignore[no-any-return]


# ─── The envelope ────────────────────────────────────────────────────────────


def test_the_document_declares_the_version_github_expects() -> None:
    document = build_sarif([_finding()], **TOOL)  # type: ignore[arg-type]

    assert document["version"] == "2.1.0"
    assert document["$schema"].endswith("sarif-2.1.0.json")
    driver = _run(document)["tool"]["driver"]
    assert driver["name"] == "GreenSecOps (docker)"
    assert driver["version"] == "1.2.3"


def test_a_clean_scan_is_a_valid_empty_report() -> None:
    """Not an error — it is how last run's alerts get closed.

    Refusing to produce a document for zero findings would leave every alert
    GitHub raised previously open forever, because nothing would ever tell it
    they were gone.
    """
    document = build_sarif([], **TOOL)  # type: ignore[arg-type]

    assert _results(document) == []
    assert _rules(document) == []
    assert document["version"] == "2.1.0"


# ─── Severity ────────────────────────────────────────────────────────────────


def test_five_severities_map_onto_the_three_sarif_levels() -> None:
    levels = {
        severity: _results(build_sarif([_finding(severity=severity)], **TOOL))[0][  # type: ignore[arg-type]
            "level"
        ]
        for severity in Severity
    }
    assert levels == {
        Severity.critical: "error",
        Severity.high: "error",
        Severity.medium: "warning",
        Severity.low: "note",
        Severity.info: "note",
    }


def test_critical_outranks_high_even_though_both_are_errors() -> None:
    """The ranking SARIF's three levels cannot express moves to
    ``security-severity``, which is what the security tab sorts and filters by.
    """
    scores = [
        float(
            _rules(build_sarif([_finding(severity=severity)], **TOOL))[0][  # type: ignore[arg-type]
                "properties"
            ]["security-severity"]
        )
        for severity in (Severity.critical, Severity.high, Severity.medium)
    ]
    assert scores == sorted(scores, reverse=True)
    # 9.0+ is the bucket GitHub labels "Critical"; 7.0+ "High".
    assert scores[0] >= 9.0
    assert 7.0 <= scores[1] < 9.0


# ─── Rules ───────────────────────────────────────────────────────────────────


def test_a_rule_is_described_once_and_referenced_by_index() -> None:
    document = build_sarif(
        [_finding(line_start=3), _finding(line_start=9)],
        **TOOL,  # type: ignore[arg-type]
    )

    assert len(_rules(document)) == 1
    assert len(_results(document)) == 2
    assert [r["ruleIndex"] for r in _results(document)] == [0, 0]
    assert _results(document)[0]["ruleId"] == _rules(document)[0]["id"]


def test_the_same_slug_in_two_categories_is_two_rules() -> None:
    """``rds_not_encrypted`` is a real rule in more than one place.

    An un-namespaced id would merge them into one alert carrying one of the
    two descriptions, and a reader would be told the wrong thing about half
    the findings.
    """
    document = build_sarif(
        [
            _finding(category=Category.security),
            _finding(category=Category.reliability),
        ],
        **TOOL,  # type: ignore[arg-type]
    )

    ids = [r["id"] for r in _rules(document)]
    assert ids == [
        "greensecops/security/unpinned_base_image",
        "greensecops/reliability/unpinned_base_image",
    ]
    assert [r["ruleIndex"] for r in _results(document)] == [0, 1]


def test_a_rule_carries_its_category_as_a_filterable_tag() -> None:
    rule = _rules(build_sarif([_finding(category=Category.energy)], **TOOL))[0]  # type: ignore[arg-type]

    assert "energy" in rule["properties"]["tags"]
    assert rule["shortDescription"]["text"] == "Base image is not pinned"
    assert rule["fullDescription"]["text"] == "A floating tag can change under you."


# ─── Locations ───────────────────────────────────────────────────────────────


def test_a_result_points_at_the_file_and_line() -> None:
    location = _results(build_sarif([_finding()], **TOOL))[0]["locations"][0]  # type: ignore[arg-type]
    physical = location["physicalLocation"]

    assert physical["artifactLocation"]["uri"] == "Dockerfile"
    assert physical["region"] == {"startLine": 3, "endLine": 3}


def test_a_finding_with_no_line_is_anchored_at_the_top_of_the_file() -> None:
    """SARIF requires a positive ``startLine`` and GitHub drops a result whose
    region is invalid — the top of the right file beats not appearing at all.
    """
    region = _results(build_sarif([_finding(line_start=None, line_end=None)], **TOOL))[  # type: ignore[arg-type]
        0
    ]["locations"][0]["physicalLocation"]["region"]

    assert region == {"startLine": 1}


def test_an_end_line_before_the_start_is_dropped_rather_than_written() -> None:
    region = _results(build_sarif([_finding(line_start=10, line_end=2)], **TOOL))[0][  # type: ignore[arg-type]
        "locations"
    ][0]["physicalLocation"]["region"]

    assert region == {"startLine": 10}


# ─── Fingerprints ────────────────────────────────────────────────────────────


def test_the_fingerprint_is_what_keeps_an_alert_the_same_alert() -> None:
    """Without it an unrelated edit above a finding closes the alert and opens
    a new one, losing whatever the team had already dismissed.
    """
    result = _results(build_sarif([_finding(fingerprint="deadbeef")], **TOOL))[0]  # type: ignore[arg-type]

    assert result["partialFingerprints"] == {"greensecopsFingerprint/v1": "deadbeef"}


def test_no_fingerprint_means_the_field_is_absent_not_empty() -> None:
    """An empty fingerprint would match every other finding lacking one."""
    result = _results(build_sarif([_finding(fingerprint=None)], **TOOL))[0]  # type: ignore[arg-type]

    assert "partialFingerprints" not in result
