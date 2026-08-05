"""Compose file → JSON document with source line spans, for OPA evaluation.

Parsed in ruamel's **round-trip** mode, because that is the only mode which
keeps position data (``node.lc``). Line attribution belongs in the parser,
matching how the Terraform engine gets it from
``hcl2.loads(..., with_meta=True)`` — and, since the workflow engine was moved
onto the same footing, how ``opa.evaluator.parse_workflow_yaml`` does it too.
The conversion itself lives in ``services/yaml_positions`` so the two YAML
engines share one implementation.

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

from app.services.yaml_positions import convert_with_positions, key_line, stamp_span

logger = logging.getLogger(__name__)

_SOURCE_FILE_KEY = "__docker_file"


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

    converted, _, _ = convert_with_positions(loaded, 1)
    # The converter is recursive over an untyped tree, so its value is Any; the
    # top-level node is known to be a mapping because of the isinstance guard
    # above, and narrowing it here keeps the public return type honest.
    document: dict[str, Any] = converted

    services = loaded.get("services")
    converted_services = document.get("services")
    if isinstance(services, dict) and isinstance(converted_services, dict):
        for name, value in services.items():
            entry = converted_services.get(str(name))
            if not isinstance(entry, dict):
                # ``api:`` with no body parses to None — nothing to stamp.
                continue
            stamp_span(entry, value, key_line(services, name, 1))

    document[_SOURCE_FILE_KEY] = path
    return document
