"""GitHub Actions workflow YAML → the JSON document OPA evaluates.

Split out of ``opa.evaluator`` so it can be imported without pulling in httpx
and the app settings: ``scripts/validate_examples.py`` runs in the OPA CI job,
which installs only ruamel and python-hcl2, and it used to carry its own copy
of this parser as a result. A copy of a parser is a copy that drifts — a rule
reading the position keys stamped below would have had its METADATA ``bad``
example silently fail to fire there while working in production. Same reasoning
as ``app/core/rego_metadata.py``.
"""

import io
import logging
import re
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from app.services.yaml_positions import convert_with_positions, key_line, stamp_span

logger = logging.getLogger(__name__)

USES_COMMENT_KEY = "__uses_comment__"

# `uses: owner/action@<sha> # v1.2.3` — the trailing comment is the only record
# of which version a SHA pin is meant to be, and it is the half a human reads.
# ruamel keeps comments in the round-trip tree, but `convert_with_positions`
# produces plain JSON and drops them, so without this they never reach a rule.
_USES_COMMENT_RE = re.compile(
    r"""^\s*(?:-\s+)?uses:\s*(?P<uses>\S+)\s+\#\s*(?P<comment>.*?)\s*$"""
)


def _uses_comments(raw_content: str) -> dict[int, tuple[str, str]]:
    """1-based line number → (uses value as written, trailing comment)."""
    found: dict[int, tuple[str, str]] = {}
    for offset, line in enumerate(raw_content.splitlines()):
        match = _USES_COMMENT_RE.match(line)
        if match:
            found[offset + 1] = (match.group("uses"), match.group("comment"))
    return found


def _stamp_steps(
    job_node: Any,
    job_entry: dict[str, Any],
    fallback: int,
    uses_comments: dict[int, tuple[str, str]],
) -> None:
    """Record each step's span, and its ``uses:`` version comment, on the job."""
    steps = job_node.get("steps") if isinstance(job_node, dict) else None
    converted = job_entry.get("steps")
    if not (isinstance(steps, list) and isinstance(converted, list)):
        return
    for index, step in enumerate(steps):
        if index >= len(converted):
            break
        entry = converted[index]
        if not isinstance(entry, dict):
            # `- run: x` with a null body, or a malformed entry.
            continue
        step_line = key_line(steps, index, fallback)
        stamp_span(entry, step, step_line)
        _stamp_uses_comment(entry, step, step_line, uses_comments)


def _stamp_uses_comment(
    entry: dict[str, Any],
    step_node: Any,
    step_line: int,
    uses_comments: dict[int, tuple[str, str]],
) -> None:
    """Attach the trailing comment on this step's ``uses:`` line, if any.

    The position comes from ruamel, which is exact; only the text of that one
    line is read with a regex. Reconstructing the mapping from a whole-file
    regex instead would have to re-derive which step each match belongs to,
    which is the kind of implicit coupling that rots the first time a workflow
    uses flow style.

    The comment is attached only when the token on the line matches the parsed
    ``uses`` value. A mismatch means the line was not what it looked like —
    flow style, an anchor, a folded scalar — and dropping the comment is the
    safe direction: a missing comment makes ``ref_version_mismatch`` silent,
    where a mis-attributed one would make it wrong.
    """
    uses = entry.get("uses")
    if not isinstance(uses, str):
        return
    line = (
        key_line(step_node, "uses", step_line)
        if hasattr(step_node, "lc")
        else step_line
    )
    candidate = uses_comments.get(line)
    if candidate is None:
        return
    written, comment = candidate
    if written.strip("\"'") != uses:
        return
    entry[USES_COMMENT_KEY] = comment


def parse_workflow_yaml(raw_content: str) -> dict[str, Any] | None:
    """Parse a workflow into the document OPA evaluates, with line spans.

    ruamel defaults to the YAML 1.2 core schema, where the bare ``on:`` key
    stays the string ``"on"`` instead of being coerced to the boolean ``True``
    (PyYAML's YAML 1.1 behaviour). That coercion silently broke every rule
    reading ``input.on`` — pr_target_injection and missing_concurrency never
    matched a real workflow. Round-trip mode keeps that schema, so the fix
    holds; ``convert_with_positions`` turns the result back into plain
    dict/list/scalar types so the document stays JSON-serialisable for the OPA
    request body.

    Round-trip mode is used rather than ``typ="safe"`` because it is the only
    one that retains ``node.lc``. Positions are stamped onto **each job and
    each step, and nothing else** — the same two-node discipline
    ``docker/compose_parser`` applies to services. Stamping recursively would
    put a ``__start_line__`` key inside every mapping a rule iterates,
    including ``env`` blocks whose keys are environment variable names, and
    inside ``input.jobs`` itself, where ``missing_top_level_permissions``
    iterates job names.
    """
    yaml_parser = YAML(typ="rt")
    try:
        loaded = yaml_parser.load(io.StringIO(raw_content))
    except YAMLError as exc:
        logger.warning("Failed to parse workflow YAML: %s", exc)
        return None
    if not isinstance(loaded, dict):
        return None

    converted, _, _ = convert_with_positions(loaded, 1)
    document: dict[str, Any] = converted
    uses_comments = _uses_comments(raw_content)

    jobs = loaded.get("jobs")
    converted_jobs = document.get("jobs")
    if isinstance(jobs, dict) and isinstance(converted_jobs, dict):
        for name, job in jobs.items():
            entry = converted_jobs.get(str(name))
            if not isinstance(entry, dict):
                # `build:` with no body parses to None — nothing to stamp.
                continue
            start = key_line(jobs, name, 1)
            stamp_span(entry, job, start)
            _stamp_steps(job, entry, start, uses_comments)

    return document
