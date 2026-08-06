"""Dockerfile → JSON instruction stream, for OPA evaluation.

Hand-rolled rather than built on ``dockerfile-parse``/``dockerfile``: every
other engine gets its document from a parser it already depends on (ruamel for
YAML, python-hcl2 for Terraform), but no Dockerfile parser is in the dependency
set, and ``backend/pyproject.toml`` is a restricted file (see CONTRIBUTING.md).
The grammar is small enough that a parser is cheaper than a dependency
negotiation, and hand-rolling means heredocs and the ``escape`` directive are
handled the way *this* engine needs rather than the way a library that was
written for label/env rewriting happens to.

The emitted document mirrors the Terraform convention in
``services/terraform/hcl_parser.py``: source metadata rides along inside the
document under double-underscore keys (``__docker_file``, ``__start_line__``,
``__end_line__``) so a Rego rule can report exactly where a violation came from
without a second lookup table.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors ``hcl_parser._SOURCE_FILE_KEY``. A Dockerfile instruction can't
# produce a key at all (the document shape is ours, not the user's), so unlike
# the HCL case there is no collision to reason about — the name is chosen for
# symmetry with the Terraform engine, not out of necessity.
_SOURCE_FILE_KEY = "__docker_file"

# ``# escape=X`` and ``# syntax=...`` are *parser directives*, not comments,
# and are only honoured before the first non-comment line. Docker restricts
# the escape character to backslash or backtick.
_DIRECTIVE_RE = re.compile(
    r"^#\s*(?P<name>escape|syntax)\s*=\s*(?P<value>\S+)\s*$", re.I
)
_VALID_ESCAPE_CHARS = {"\\", "`"}

# A leading ``--flag`` or ``--flag=value`` on an instruction (``RUN --mount=…``,
# ``COPY --from=builder``). Captured separately so a rule matching on the
# command text isn't confused by them.
_FLAG_RE = re.compile(r"^--(?P<key>[a-zA-Z0-9-]+)(?:=(?P<value>\S*))?$")

# ``<<EOF``, ``<<-EOF``, ``<<"EOF"``, ``<<'EOF'`` — BuildKit heredocs.
_HEREDOC_RE = re.compile(
    r"<<(?P<dash>-?)(?P<quote>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)"
)

_INSTRUCTION_RE = re.compile(
    r"^(?P<instruction>[A-Za-z][A-Za-z0-9_]*)(?:\s+(?P<value>.*))?$", re.S
)

# ``FROM image[:tag|@digest] [AS name]``
_FROM_RE = re.compile(
    r"^(?P<image>\S+?)(?::(?P<tag>[^@\s]+))?(?:@(?P<digest>\S+))?(?:\s+AS\s+(?P<name>\S+))?$",
    re.I,
)


def _read_directives(lines: list[str]) -> tuple[str, str | None, int]:
    """Consume leading parser directives.

    Returns ``(escape_char, syntax, first_content_index)``. Directives stop at
    the first line that is not a directive comment — a plain ``# comment``
    before ``# escape=`` means the escape directive is no longer honoured,
    which is Docker's actual behaviour and a real (if rare) source of
    surprise.
    """
    escape_char = "\\"
    syntax: str | None = None
    index = 0
    for index, raw in enumerate(lines):  # noqa: B007 — index is used after the loop
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("#"):
            return escape_char, syntax, index
        match = _DIRECTIVE_RE.match(line)
        if match is None:
            # A non-directive comment closes the directive section.
            return escape_char, syntax, index
        if match.group("name").lower() == "escape":
            value = match.group("value")
            if value in _VALID_ESCAPE_CHARS:
                escape_char = value
        else:
            syntax = match.group("value")
    return escape_char, syntax, len(lines)


def _split_flags(value: str) -> tuple[dict[str, str], str]:
    """Peel leading ``--flag[=value]`` tokens off an instruction's argument."""
    flags: dict[str, str] = {}
    rest = value
    while rest:
        head, _, tail = rest.partition(" ")
        match = _FLAG_RE.match(head)
        if match is None:
            break
        flags[match.group("key")] = match.group("value") or "true"
        rest = tail.strip()
    return flags, rest


def _heredoc_tags(text: str) -> list[str]:
    return [m.group("tag") for m in _HEREDOC_RE.finditer(text)]


def _join_continuations(
    lines: list[str], start: int, escape_char: str
) -> tuple[str, int]:
    """Fold one logical instruction starting at ``start`` (0-based).

    Returns ``(logical_text, last_index_consumed)``. Blank lines and comments
    *inside* a continuation are dropped, matching Docker: they do not terminate
    the instruction.
    """
    parts: list[str] = []
    index = start
    last = start
    while index < len(lines):
        current = lines[index].rstrip()
        last = index
        if current.endswith(escape_char):
            parts.append(current[: -len(escape_char)].strip())
            index += 1
            while index < len(lines):
                peek = lines[index].strip()
                if peek and not peek.startswith("#"):
                    break
                last = index
                index += 1
            continue
        parts.append(current.strip())
        break
    return " ".join(part for part in parts if part), last


def _consume_heredocs(
    lines: list[str], start: int, tags: list[str]
) -> tuple[list[str], int]:
    """Read heredoc bodies following an instruction; return (body, last index)."""
    body: list[str] = []
    index = start
    pending = list(tags)
    while index < len(lines) and pending:
        line = lines[index]
        if line.strip() == pending[0]:
            pending.pop(0)
        else:
            body.append(line)
        index += 1
    return body, index - 1


def _parse_from(value: str) -> dict[str, Any]:
    match = _FROM_RE.match(value.strip())
    if match is None:
        return {"image": value.strip(), "tag": None, "digest": None, "name": None}
    return {
        "image": match.group("image"),
        "tag": match.group("tag"),
        "digest": match.group("digest"),
        "name": match.group("name"),
    }


def parse_dockerfile_content(path: str, raw_content: str) -> dict[str, Any] | None:
    """Parse one Dockerfile into the document OPA evaluates.

    Returns ``None`` (rather than raising) when the file yields no instructions
    at all, so one unparseable file in a target doesn't abort the whole scan —
    mirrors ``hcl_parser.parse_terraform_content`` and
    ``opa.evaluator.parse_workflow_yaml``.

    Shape::

        {"__docker_file": "backend/Dockerfile",
         "syntax": "docker/dockerfile:1",
         "final_stage": 1,
         "stages": [{"index": 0, "name": "builder", "image": "python",
                     "tag": "3.12", "digest": None, "is_final": False,
                     "__start_line__": 1, "__end_line__": 9}, ...],
         "instructions": [{"instruction": "RUN", "value": "apt-get update",
                           "flags": {}, "stage": 0, "heredoc": None,
                           "__start_line__": 4, "__end_line__": 6}, ...]}
    """
    lines = raw_content.splitlines()
    escape_char, syntax, cursor = _read_directives(lines)

    instructions: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    stage_index: int | None = None

    while cursor < len(lines):
        stripped = lines[cursor].strip()
        if not stripped or stripped.startswith("#"):
            cursor += 1
            continue

        start_line = cursor + 1
        logical, last = _join_continuations(lines, cursor, escape_char)
        cursor = last + 1

        match = _INSTRUCTION_RE.match(logical)
        if match is None:
            logger.debug(
                "Skipping unparseable Dockerfile line in %s: %r", path, logical
            )
            continue

        keyword = match.group("instruction").upper()
        value = (match.group("value") or "").strip()
        flags, value = _split_flags(value)

        heredoc: str | None = None
        tags = _heredoc_tags(value)
        if tags:
            body, last = _consume_heredocs(lines, cursor, tags)
            cursor = last + 1
            heredoc = "\n".join(body)

        if keyword == "FROM":
            parsed = _parse_from(value)
            stage_index = len(stages)
            stages.append(
                {
                    "index": stage_index,
                    "name": parsed["name"],
                    "image": parsed["image"],
                    "tag": parsed["tag"],
                    "digest": parsed["digest"],
                    "platform": flags.get("platform"),
                    # Rewritten once the whole file is parsed.
                    "is_final": False,
                    "__start_line__": start_line,
                    "__end_line__": last + 1,
                }
            )

        instructions.append(
            {
                "instruction": keyword,
                "value": value,
                "flags": flags,
                "stage": stage_index,
                "heredoc": heredoc,
                "__start_line__": start_line,
                "__end_line__": last + 1,
            }
        )

    if not instructions:
        logger.warning("Dockerfile %s produced no instructions; skipping", path)
        return None

    # A stage ends where the next one begins. Computing it here rather than in
    # Rego keeps "which stage does this line belong to" in one place.
    for position, stage in enumerate(stages):
        following = (
            stages[position + 1]["__start_line__"] - 1
            if position + 1 < len(stages)
            else None
        )
        stage["__end_line__"] = following or instructions[-1]["__end_line__"]

    # The final stage is the last FROM. This is what `docker build` produces
    # without an explicit `--target`, and is the stage whose USER, HEALTHCHECK
    # and installed toolchain actually ship — rules about the shipped image
    # must scope to it or they fire on builder stages that legitimately run as
    # root. `--target` builds are not modelled; see the module docstring in
    # merge.py for the engine's stance on build-time configuration.
    final_stage = stages[-1]["index"] if stages else None
    if stages:
        stages[-1]["is_final"] = True

    return {
        _SOURCE_FILE_KEY: path,
        "syntax": syntax,
        "escape": escape_char,
        "final_stage": final_stage,
        "stages": stages,
        "instructions": instructions,
    }
