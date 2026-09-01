"""Findings as SARIF, so GitHub Code Scanning can show them.

The product already grades a repository; this is the same findings expressed
in the one format GitHub's security tab reads. It exists so a team can adopt
GreenSecOps as a workflow — ``upload-sarif`` on their own runner — rather than
only as an installed App, and so the findings land in the PR review UI beside
whatever else that team already scans with.

Deliberately pure: no session, no HTTP, no engine imports. One engine's rows
are flattened to :class:`SarifFinding` by the caller, and everything below
treats them identically — which is what stops "how severe is this" or "what
identifies this finding" from acquiring a second, per-engine answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.enums import Category, Severity

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

# SARIF has three levels; we grade on five. Critical and high are both things
# that should fail a review, so both are `error` — the ranking between them is
# not lost, it moves to `security-severity` below, which is what GitHub
# actually sorts and filters the security tab by.
_LEVEL_OF_SEVERITY: dict[Severity, str] = {
    Severity.critical: "error",
    Severity.high: "error",
    Severity.medium: "warning",
    Severity.low: "note",
    Severity.info: "note",
}

# GitHub reads `security-severity` as a CVSS-style 0–10 score and buckets it:
# 9.0+ critical, 7.0+ high, 4.0+ medium, 0.1+ low. The numbers below are chosen
# to land in the bucket whose name matches ours, so a `high` finding reads as
# "High" in the security tab rather than being re-ranked by a scale it was
# never measured on.
_SECURITY_SEVERITY: dict[Severity, str] = {
    Severity.critical: "9.5",
    Severity.high: "7.5",
    Severity.medium: "5.0",
    Severity.low: "2.0",
    Severity.info: "0.5",
}


@dataclass(frozen=True)
class SarifFinding:
    """One violation, reduced to what SARIF needs to describe it.

    Every engine's finding row collapses to this. The fields it keeps are the
    ones SARIF has somewhere to put: a rule, a severity, a sentence, and a
    place in a file. The ones it drops — the target id, the scan it came from,
    the fix that may exist for it — have no representation in the format and
    belong to the application, not to the report.

    ``file_path`` is repository-relative because that is the only thing a
    checkout on the runner can resolve. ``fingerprint`` is what lets GitHub
    recognise a finding across commits instead of closing and reopening it
    every time the file moves a line.
    """

    rule_slug: str
    rule_title: str
    rule_description: str
    severity: Severity
    category: Category
    message: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    fingerprint: str | None = None

    @property
    def rule_id(self) -> str:
        """The id GitHub groups alerts by, namespaced per category.

        The same slug can exist in two categories, and an un-namespaced id
        would merge two different rules into one alert with one description.
        """
        return f"greensecops/{self.category.value}/{self.rule_slug}"


def _region(finding: SarifFinding) -> dict[str, Any]:
    """Where in the file, as far as we honestly know.

    A line number is the whole of it: the analysers work on parsed structure
    rather than character offsets, so claiming a column would be inventing
    precision. Line 1 is the fallback because SARIF requires a positive
    ``startLine`` and GitHub silently drops a result whose region is invalid —
    a finding shown against the top of the right file is far better than one
    that never appears.
    """
    start = finding.line_start or 1
    region: dict[str, Any] = {"startLine": start}
    if finding.line_end and finding.line_end >= start:
        region["endLine"] = finding.line_end
    return region


def _rule_descriptor(finding: SarifFinding) -> dict[str, Any]:
    return {
        "id": finding.rule_id,
        "name": finding.rule_slug,
        "shortDescription": {"text": finding.rule_title},
        "fullDescription": {"text": finding.rule_description},
        "defaultConfiguration": {"level": _LEVEL_OF_SEVERITY[finding.severity]},
        "properties": {
            # `tags` is what the security tab filters on; the category is the
            # axis we grade against, so it is the useful thing to filter by.
            "tags": [finding.category.value, finding.severity.value],
            "security-severity": _SECURITY_SEVERITY[finding.severity],
        },
    }


def _result(finding: SarifFinding, rule_index: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        # Both the id and the index: the id is what a human reads in the diff,
        # the index is what the format uses to reach the descriptor.
        "ruleIndex": rule_index,
        "level": _LEVEL_OF_SEVERITY[finding.severity],
        "message": {"text": finding.message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.file_path},
                    "region": _region(finding),
                }
            }
        ],
    }
    if finding.fingerprint:
        # Without this GitHub falls back to matching on the surrounding source,
        # so an unrelated edit above a finding closes the old alert and opens a
        # new one — and any dismissal the team made is lost with it. Ours is
        # already stable across re-scans by construction (see
        # ``services/deduplication.compute_fingerprint``), which is exactly
        # what this field wants.
        result["partialFingerprints"] = {
            "greensecopsFingerprint/v1": finding.fingerprint
        }
    return result


def build_sarif(
    findings: list[SarifFinding],
    *,
    tool_name: str,
    tool_version: str,
    information_uri: str,
) -> dict[str, Any]:
    """One SARIF 2.1.0 log for ``findings``, ready to hand to ``upload-sarif``.

    Rules are emitted once each and referenced by index, which is the format's
    own arrangement rather than an optimisation: a rule's description belongs
    to the rule, and repeating it per result invites two results to disagree
    about what the same rule means.

    An empty list is a valid and meaningful report, not an error — it is how a
    clean scan tells GitHub to close the alerts it raised last time. Returning
    nothing instead would leave stale alerts open forever.
    """
    rule_indexes: dict[str, int] = {}
    rules: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for finding in findings:
        index = rule_indexes.get(finding.rule_id)
        if index is None:
            index = len(rules)
            rule_indexes[finding.rule_id] = index
            rules.append(_rule_descriptor(finding))
        results.append(_result(finding, index))

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": tool_version,
                        "informationUri": information_uri,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
