"""Reading what a fix-generation model sent back.

Every engine's fix prompt asks for the same XML-delimited envelope — a
``<full_content>`` block holding the rewritten file, and an optional
``<unfixed>`` block listing the issues the model could not resolve — so every
engine needs the same three pieces of parsing.

These lived in ``workers/tasks/fix_generation.py`` and were imported *by their
private names* from ``services/file_fix_generation.py``, which put a service on
the wrong side of the layering: services are what workers are built from, not the
other way round. Parsing a model's reply is not worker behaviour, so it lives
here with the prompts that asked for the shape.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_FULL_CONTENT_RE = re.compile(r"<full_content>\n?(.*?)</full_content>", re.DOTALL)
_UNFIXED_RE = re.compile(r"<unfixed>\n?(.*?)</unfixed>", re.DOTALL)
_UNFIXED_LINE_RE = re.compile(r"^\s*(\d+)\s*:\s*(.+?)\s*$")

# A reason longer than this is the model rambling, not explaining; the column it
# lands in (`Issue.manual_work_note`) is 1024 anyway.
_MAX_REASON = 1024


def parse_full_content(content: str) -> str:
    """The rewritten file from the model's ``<full_content>`` block, or ``""``.

    An empty return is the caller's signal to fail the fix: delivery pushes this
    text to a real branch, so half a file is worse than none.
    """
    match = _FULL_CONTENT_RE.search(content)
    full_content = match.group(1) if match else ""

    if not full_content:
        logger.warning(
            "LLM response missing <full_content> block. First 500 chars: %r",
            content[:500],
        )
    logger.info("Parsed LLM response: full_content=%d chars", len(full_content))
    return full_content


def parse_unfixed_issues(content: str) -> dict[int, str]:
    """The ``<unfixed>`` block: 1-based prompt issue index -> reason.

    Absent or empty block (every issue was fixed) returns ``{}``.
    """
    match = _UNFIXED_RE.search(content)
    if not match:
        return {}
    unfixed: dict[int, str] = {}
    for line in match.group(1).splitlines():
        line_match = _UNFIXED_LINE_RE.match(line)
        if line_match:
            unfixed[int(line_match.group(1))] = line_match.group(2)[:_MAX_REASON]
    return unfixed


def restore_trailing_whitespace(original: str, patched: str) -> str:
    """Restore original trailing whitespace on lines that only differ in it.

    LLMs routinely strip trailing whitespace when regenerating file content. For
    lines where the stripped versions are identical, keep the original so the
    delivered diff contains only meaningful changes.
    """
    orig_lines = original.split("\n")
    new_lines = patched.split("\n")
    result = []
    for i, new_line in enumerate(new_lines):
        if (
            i < len(orig_lines)
            and new_line.rstrip() == orig_lines[i].rstrip()
            and new_line != orig_lines[i]
        ):
            result.append(orig_lines[i])
        else:
            result.append(new_line)
    return "\n".join(result)
