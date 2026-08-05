"""Convert a ruamel round-trip YAML tree to plain types, keeping line spans.

Round-trip mode (``YAML(typ="rt")``) is the only ruamel mode that retains
position data on its nodes (``node.lc``), but its values are ruamel's own
subclasses rather than plain ``dict``/``list``/scalars. Every engine that wants
to tell a rule *where* a finding is therefore needs the same two things: the
positions, and a JSON-serialisable document to send to OPA.

This was written for Compose and is now shared with the CI-workflow engine —
``compose_parser``'s docstring called out the divergence (the workflow engine
got its lines from a *second* parse after evaluation) and this is what closes
it. Round-trip mode still yields the YAML 1.2 core schema, so the
``on:``-becomes-``True`` coercion that ``parse_workflow_yaml`` documents does
not come back with it.

The converter is deliberately **pure** — it never injects a key. Stamping is
each engine's own narrowly-targeted second pass over the nodes it wants
attributable, because injecting positions everywhere would put a
``__start_line__`` key inside every mapping a rule iterates, including the
``env`` blocks whose keys are environment variable names.
"""

from typing import Any

# Scalars that survive ``json.dumps`` untouched. ruamel's round-trip scalar
# types (ScalarString, ScalarInt, ScalarFloat) subclass these, so they pass;
# anything else (notably a bare ``date``, which YAML types natively) is
# stringified rather than allowed to blow up the OPA request.
_JSON_SCALARS = (str, int, float, bool, type(None))

START_LINE_KEY = "__start_line__"
END_LINE_KEY = "__end_line__"


def convert_with_positions(node: Any, fallback_line: int) -> tuple[Any, int, int]:
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
            child, child_start, child_end = convert_with_positions(value, key_line)
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
            child, child_start, child_end = convert_with_positions(value, item_line)
            items.append(child)
            start = min(start, item_line, child_start)
            end = max(end, item_line, child_end)
        return items, start, end

    if not isinstance(node, _JSON_SCALARS):
        return str(node), own_line, own_line
    return node, own_line, own_line


def key_line(container: Any, key: Any, fallback: int) -> int:
    """1-based line of ``key`` within a round-trip mapping or sequence."""
    positions = getattr(getattr(container, "lc", None), "data", None)
    if not positions:
        return fallback
    if isinstance(container, list):
        if isinstance(key, int) and key < len(positions):
            return int(positions[key][0]) + 1
        return fallback
    if key in positions:
        return int(positions[key][0]) + 1
    return fallback


def stamp_span(entry: dict[str, Any], node: Any, start: int) -> None:
    """Record ``node``'s span on the already-converted ``entry``.

    ``start`` is the line of the key or sequence item that introduced the node,
    which is what a finding should point at — the ``api:`` line rather than
    wherever inside it the offending value happens to sit.

    The end line is approximate for a block scalar. ruamel records where a
    ``run: |`` starts but not where its body ends, so a span covering one stops
    at the ``run:`` line rather than the last line of the script. Start is what
    a finding is anchored on, so this is a cosmetic limit on the span rather
    than a wrong attribution.
    """
    _, _, end = convert_with_positions(node, start)
    entry[START_LINE_KEY] = start
    entry[END_LINE_KEY] = max(end, start)
