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
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from app.services.yaml_positions import convert_with_positions, key_line, stamp_span

logger = logging.getLogger(__name__)


def _stamp_steps(job_node: Any, job_entry: dict[str, Any], fallback: int) -> None:
    """Record each step's span on the converted job."""
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
        stamp_span(entry, step, key_line(steps, index, fallback))


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
            _stamp_steps(job, entry, start)

    return document
