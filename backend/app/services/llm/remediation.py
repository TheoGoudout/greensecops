"""The rule author's remediation prose, rendered for a fix prompt.

Every Rego policy carries a ``custom.examples.fix`` block that says not just
what to change but the conditions that make the change correct. The fix prompts
used to send only the finding's one-line message, and the model reinvented the
rest — which is how ``read_only: true`` landed on a postgres service with no
tmpfs, plain ``paths:`` filters landed on required status checks, and
``restart: always`` landed on a one-shot test runner. Each of those is the
caveat the rule's own fix text spells out.

Deduplicated by slug, because a finding is per-service (or per-job) and a rule
is not: one Compose file produced twenty-one ``compose_service_not_hardened``
findings, and twenty-one copies of the same paragraph would crowd out the file
the model is supposed to be rewriting.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_HEADER = (
    "**How to fix these rules** — written by the author of each rule. Follow it,"
    " including its conditions and exceptions: where the guidance says a change"
    " is only correct alongside something else, or only for some kinds of"
    " service or job, that qualification is the difference between a fix and an"
    " outage. Where it tells you not to make the change in a case that matches"
    " this file, report the finding under <unfixed> instead of forcing it."
)


def remediation_block(findings: Sequence[Any]) -> str:
    """The remediation text for the rules behind ``findings``, once each.

    Takes any engine's finding rows — each needs a ``rule`` carrying a ``slug``
    and a ``remediation``, and nothing else — so the four prompt builders share
    one implementation rather than four that drift.

    Returns "" when no finding carries a rule with remediation, so a caller can
    append it unconditionally. Rows seeded before ``rule.remediation`` existed
    have none; the next catalog seed fills them in.
    """
    seen: dict[str, str] = {}
    for finding in findings:
        rule = getattr(finding, "rule", None)
        if rule is None:
            continue
        text = (getattr(rule, "remediation", None) or "").strip()
        if text and rule.slug not in seen:
            seen[rule.slug] = text
    if not seen:
        return ""
    body = "\n".join(f"- `{slug}`: {text}" for slug, text in sorted(seen.items()))
    return f"\n\n{_HEADER}\n{body}"
