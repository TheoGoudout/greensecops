"""Attach GitHub-derived action metadata to a parsed workflow document.

Kept stdlib-only, and separate from ``github/action_metadata.py`` which does the
API calls, for the same reason ``workflow_parser`` is separate from the
evaluator: ``scripts/validate_examples.py`` runs in the OPA CI job with only
ruamel and python-hcl2 installed, and it has to attach the fixtures declared in
a rule's METADATA through *this* function rather than a copy of it. One
definition of where enrichment lives means a rule's ``bad`` example is tested
against the same document shape production builds.
"""

from collections.abc import Mapping
from typing import Any

# Top level rather than stamped onto each step. Two reasons: an action used by
# thirty steps costs one entry instead of thirty, and `workflow_parser` is
# deliberately strict about which nodes get dunder keys — a rule iterating a
# step's keys would otherwise meet a metadata object. No rule in any engine
# iterates the document's top-level keys, so a new one here cannot make an
# existing rule fire.
ACTIONS_KEY = "__actions__"


def workflow_uses(document: Mapping[str, Any]) -> set[str]:
    """Every ``uses:`` value in ``document``, across all jobs and steps."""
    found: set[str] = set()
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return found
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        # A job calling a reusable workflow carries `uses` itself.
        job_uses = job.get("uses")
        if isinstance(job_uses, str):
            found.add(job_uses)
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                found.add(step["uses"])
    return found


def attach_action_metadata(
    document: dict[str, Any],
    metadata: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    """Attach the entries of ``metadata`` naming a ``uses:`` this document has.

    Filtering to the document's own references means a collector run once per
    repository can be handed to every workflow in it without the extra entries
    travelling to OPA. It also means a METADATA fixture key that matches no step
    is dropped, which surfaces loudly as "bad example does not trigger its own
    rule" rather than quietly doing nothing.

    ``None`` or an empty mapping leaves the document untouched — no key at all,
    which is what every rule's guard keys on.
    """
    if not metadata:
        return
    referenced = workflow_uses(document)
    relevant = {
        uses: dict(entry) for uses, entry in metadata.items() if uses in referenced
    }
    if relevant:
        document[ACTIONS_KEY] = relevant
