"""Compose file → JSON document with source line spans, for OPA evaluation.

Parsed in ruamel's **round-trip** mode rather than the ``typ="safe"`` used by
``opa.evaluator.parse_workflow_yaml``, because round-trip mode is the only one
that keeps position data (``node.lc``). The workflow engine gets line numbers a
different way — a *second* parse in ``static_analysis._enrich_line_numbers`` —
which works but means the analysis task has to know about YAML. Doing it here
keeps line attribution in the parser, matching how the Terraform engine gets it
from ``hcl2.loads(..., with_meta=True)``.

Round-trip mode still yields the YAML 1.2 core schema, so the ``on:``-becomes-
``True`` coercion documented in ``parse_workflow_yaml`` doesn't apply here
either. Values are converted back to plain ``dict``/``list``/scalars before
returning so the document stays JSON-serialisable for the OPA request body.
"""

import io
import logging
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

logger = logging.getLogger(__name__)

_SOURCE_FILE_KEY = "__docker_file"

# Scalars that survive ``json.dumps`` untouched. ruamel's round-trip scalar
# types (ScalarString, ScalarInt, ScalarFloat) subclass these, so they pass;
# anything else (notably a bare ``date``, which YAML types natively) is
# stringified rather than allowed to blow up the OPA request.
_JSON_SCALARS = (str, int, float, bool, type(None))


def _convert(node: Any, fallback_line: int) -> tuple[Any, int, int]:
    """Convert a ruamel node to plain types, returning its 1-based line span.

    ``fallback_line`` is used for nodes that carry no position of their own
    (scalars, and containers ruamel didn't annotate) — it is the line of the
    key or sequence entry that pointed at this node, so a span is always
    reportable even when it's approximate.
    """
    lc = getattr(node, "lc", None)
    own_line = fallback_line
    if lc is not None and getattr(lc, "line", None) is not None:
        own_line = lc.line + 1
    positions = getattr(lc, "data", None) if lc is not None else None

    if isinstance(node, dict):
        result: dict[str, Any] = {}
        start = own_line
        end = own_line
        for key, value in node.items():
            key_line = fallback_line
            if positions and key in positions:
                key_line = positions[key][0] + 1
            child, child_start, child_end = _convert(value, key_line)
            result[str(key)] = child
            start = min(start, key_line, child_start)
            end = max(end, key_line, child_end)
        return result, start, end

    if isinstance(node, list):
        items: list[Any] = []
        start = own_line
        end = own_line
        for index, value in enumerate(node):
            item_line = fallback_line
            if positions and index < len(positions):
                item_line = positions[index][0] + 1
            child, child_start, child_end = _convert(value, item_line)
            items.append(child)
            start = min(start, item_line, child_start)
            end = max(end, item_line, child_end)
        return items, start, end

    if not isinstance(node, _JSON_SCALARS):
        return str(node), own_line, own_line
    return node, own_line, own_line


def parse_compose_content(path: str, raw_content: str) -> dict[str, Any] | None:
    """Parse one Compose file, stamping each service with its source span.

    Returns ``None`` on malformed YAML or a non-mapping document rather than
    raising, so one bad file doesn't abort a scan.

    Each entry under ``services`` gains ``__start_line__`` (the line of the
    service's own key) and ``__end_line__`` (the last line of its subtree), so
    a Rego rule can report a span without re-parsing.
    """
    yaml_parser = YAML(typ="rt")
    try:
        loaded = yaml_parser.load(io.StringIO(raw_content))
    except YAMLError as exc:
        logger.warning("Failed to parse Compose file %s: %s", path, exc)
        return None
    if not isinstance(loaded, dict):
        return None

    converted, _, _ = _convert(loaded, 1)
    # _convert is recursive over an untyped tree, so its value is Any; the
    # top-level node is known to be a mapping because of the isinstance guard
    # above, and narrowing it here keeps the public return type honest.
    document: dict[str, Any] = converted

    services = loaded.get("services")
    converted_services = document.get("services")
    if isinstance(services, dict) and isinstance(converted_services, dict):
        positions = getattr(getattr(services, "lc", None), "data", None)
        for name, value in services.items():
            entry = converted_services.get(str(name))
            if not isinstance(entry, dict):
                # ``api:`` with no body parses to None — nothing to stamp.
                continue
            key_line = 1
            if positions and name in positions:
                key_line = positions[name][0] + 1
            _, _, end_line = _convert(value, key_line)
            entry["__start_line__"] = key_line
            entry["__end_line__"] = max(end_line, key_line)

    document[_SOURCE_FILE_KEY] = path
    return document
