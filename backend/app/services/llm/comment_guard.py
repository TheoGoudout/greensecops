"""Reject a rewrite that deleted a comment the original carried.

Every fix prompt says "Preserve ALL existing comments exactly as they appear",
and nothing verified it. Two fix PRs deleted the comment that explained why the
finding they were fixing was not a finding here — a Dockerfile's "No USER here,
deliberately. This image is a local/CI test harness…", a Compose file's
"mailcatcher declares no health check, so service_started is the strongest
condition available for it" — and then made the change the comment argued
against. The comment was the repository's answer to the rule, and the rewrite
erased the question along with it.

Deterministic, and cheap: the model's cooperation is not required, which is the
same reasoning as ``unrequested_pin_changes`` in the workflow flow.

Only deletion is checked. Adding, reflowing and re-indenting comments are all
fine — a fix that adds an explanatory comment is a good fix — so a comment is
matched on its text with leading markers and surrounding whitespace stripped.

The known cost: a fix that legitimately deletes a setting *and* the comment
explaining it is rejected too. That is the trade accepted here. A rejected fix
costs a regeneration; a delivered one that erased the repository's reasoning
costs a reviewer who has no way left to know what the reasoning was. The prompts
give the model the correct alternative — report the finding under ``<unfixed>``
and leave the comment alone — so this should be the rare case, and the error
message names the comments so a human can see what happened.
"""

from __future__ import annotations

import re

# `#` covers YAML, Compose, Dockerfiles, HCL and Ansible; HCL also allows `//`.
# Block comments (`/* */`) are matched by their content lines for the same
# reason the rest are: what matters is whether the prose survived, not how it
# was punctuated.
_MARKER = re.compile(r"^[\s]*(?:#+|//+|/\*+|\*+/?)\s?")
_TRAILER = re.compile(r"\s*\*/\s*$")


def _comment_text(line: str) -> str | None:
    """The prose of a whole-line comment, or None if the line is not one.

    Trailing comments (`image: foo # pinned`) are deliberately not extracted: a
    `#` inside a shell command, a URL fragment or a quoted string is not a
    comment, and telling them apart needs the parser, not a regex. Whole-line
    comments are where the reasoning lives.
    """
    stripped = line.strip()
    if not stripped.startswith(("#", "//", "/*", "*")):
        return None
    text = _TRAILER.sub("", _MARKER.sub("", stripped))
    # Collapse internal whitespace so re-indentation and re-wrapping of a
    # preserved comment do not read as a deletion.
    normalised = " ".join(text.split())
    # A bare `#`, a rule of `#####`, or an empty `*` carries no reasoning and
    # is not worth failing a fix over.
    return normalised or None


def deleted_comments(original: str, patched: str) -> list[str]:
    """Comment lines present in ``original`` and absent from ``patched``.

    Compared as a multiset would be too strict — a file that legitimately loses
    one of two identical comments (because the block they annotated was merged)
    would trip it — so this compares as sets: a comment is preserved if its text
    appears anywhere in the rewrite.
    """
    before = {
        text for text in (_comment_text(ln) for ln in original.splitlines()) if text
    }
    if not before:
        return []
    after = {
        text for text in (_comment_text(ln) for ln in patched.splitlines()) if text
    }
    return sorted(before - after)


def comment_deletion_error(original: str, patched: str) -> str | None:
    """A generation error naming the dropped comments, or None if all survived."""
    dropped = deleted_comments(original, patched)
    if not dropped:
        return None
    shown = "; ".join(f'"{text}"' for text in dropped[:3])
    if len(dropped) > 3:
        shown += f" (and {len(dropped) - 3} more)"
    return f"LLM deleted {len(dropped)} comment(s) the file carried: {shown}"
