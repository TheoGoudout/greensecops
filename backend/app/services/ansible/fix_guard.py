"""Reject an LLM rewrite that silently broke something YAML cannot express.

No other engine needs this. HCL and Dockerfiles have no equivalent of a value
that must survive *byte-identical* — but Ansible has two, and both fail
quietly rather than loudly:

* A Jinja expression is a string as far as YAML is concerned. Drop
  ``{{ ansible_facts['architecture'] }}`` from a ``get_url`` and the file still
  parses, still classifies as a task file, and downloads the wrong artifact.
* A ``!vault`` tag is what tells Ansible a blob is ciphertext. Lose the tag and
  the ciphertext becomes a literal string: the play runs, and the service comes
  up authenticating with the base64 of its own encrypted password.

Neither shows up as a parse error, so the shared ``validate`` gate — "does it
still parse?" — cannot see them. This one is differential: it compares the
rewrite against the original and requires containment **in one direction
only**, original ⊆ patched.

That direction is the whole design. A fix legitimately *adds*: ``| quote`` on
an interpolation, a ``checksum:`` built from a new variable, a ``no_log: true``.
It legitimately reorders, re-comments, and adds or removes whole tasks. What it
must never do is drop a variable reference or a tag that was there before, so
those are the only two things compared, and equality is never required.

Comparing variable *names* rather than raw expression text is likewise
deliberate: ``{{ region }}`` → ``{{ region | quote }}`` is precisely the fix
``shell_with_unquoted_variable`` asks for, and a raw-text comparison would
reject the rewrite it requested.
"""

from __future__ import annotations

import io
import re
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from app.services.ansible.discovery import classify_ansible_file

INVALID_YAML_ERROR = "LLM returned invalid Ansible YAML"
KIND_CHANGED_ERROR = "LLM rewrite changed the file's kind from {before} to {after}"
DROPPED_VARIABLES_ERROR = "LLM rewrite dropped Jinja variable(s): {names}"
DROPPED_TAGS_ERROR = "LLM rewrite dropped YAML tag(s): {tags}"

# `{{ ... }}` and `{% ... %}`. Non-greedy so two expressions on one line stay
# two, and DOTALL because a folded scalar can wrap an expression across lines.
_JINJA_SPAN_RE = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.DOTALL)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Quoted string literals inside an expression. `default('x')` holds a value, not
# a variable name, and counting `x` would make the guard reject the removal of a
# now-redundant filter — a legitimate simplification.
_STRING_LITERAL_RE = re.compile(r"'[^']*'|\"[^\"]*\"")

# Names that appear inside an expression without being variables. Jinja's own
# grammar plus its literals; anything else is either a variable or a filter,
# and filters are excluded positionally below.
_JINJA_RESERVED = frozenset(
    {
        "and",
        "as",
        "block",
        "by",
        "else",
        "elif",
        "endblock",
        "endfor",
        "endif",
        "endmacro",
        "endraw",
        "endset",
        "false",
        "filter",
        "for",
        "from",
        "if",
        "import",
        "in",
        "is",
        "macro",
        "none",
        "not",
        "or",
        "raw",
        "recursive",
        "set",
        "true",
        "with",
        "without",
    }
)


def _jinja_variables(content: str) -> set[str]:
    """Every variable name referenced by a Jinja expression in ``content``.

    Filter and test names (``| quote``, ``is defined``) and attribute accesses
    (``.stdout``) are excluded: they are not variables, and a fix is free to
    add, remove or change them. What is left is the set a rewrite must keep.
    """
    names: set[str] = set()
    for match in _JINJA_SPAN_RE.finditer(content):
        expression = match.group(1) or match.group(2) or ""
        # Blank out literals rather than delete them, so the offsets the
        # lookback below reads stay aligned with the original expression.
        expression = _STRING_LITERAL_RE.sub(lambda m: " " * len(m.group(0)), expression)
        for token in _IDENTIFIER_RE.finditer(expression):
            name = token.group(0)
            if name in _JINJA_RESERVED:
                continue
            # Look back past whitespace for the character that decides whether
            # this identifier is a variable at all.
            before = expression[: token.start()].rstrip()
            if before.endswith((".", "|")):
                # `.stdout` is an attribute of a variable already counted;
                # `| quote` is a filter. Neither is a name of its own.
                continue
            if before.endswith("is"):
                # `is defined` — a test, not a variable.
                continue
            names.add(name)
    return names


def _yaml_tags(content: str) -> set[str]:
    """Every explicit YAML tag in ``content`` (``!vault``, ``!unsafe``, …).

    Parsed rather than regex-matched: ``!vault`` inside a comment or a quoted
    string is not a tag, and treating it as one would make the guard reject a
    rewrite for keeping a string it never had to keep.
    """
    try:
        documents = list(YAML(typ="rt").load_all(io.StringIO(content)))
    except YAMLError:
        return set()
    tags: set[str] = set()
    for document in documents:
        _collect_tags(document, tags)
    return tags


def _collect_tags(node: Any, tags: set[str]) -> None:
    # ruamel hands back a `Tag` object on some nodes and a bare string on
    # others, so read `.value` when it is there and fall back to the string.
    tag = getattr(node, "tag", None)
    if tag is not None:
        value = getattr(tag, "value", tag)
        if isinstance(value, str) and value.startswith("!"):
            tags.add(value)
    if isinstance(node, dict):
        for key, value in node.items():
            _collect_tags(key, tags)
            _collect_tags(value, tags)
    elif isinstance(node, list):
        for item in node:
            _collect_tags(item, tags)


def validate_ansible_fix(file_path: str, original: str, patched: str) -> str | None:
    """An error message when ``patched`` is not a safe rewrite, else ``None``.

    Called by the shared generation flow before the content is ever stored, so
    a rejected rewrite fails the fix rather than reaching delivery.
    """
    kind_after = classify_ansible_file(file_path, patched)
    if kind_after is None:
        # Either it no longer parses, or it parses into something that is not
        # Ansible any more. The classifier cannot tell those apart and the
        # outcome is the same: not deliverable.
        return INVALID_YAML_ERROR

    kind_before = classify_ansible_file(file_path, original)
    if kind_before is not None and kind_before != kind_after:
        return KIND_CHANGED_ERROR.format(before=kind_before, after=kind_after)

    dropped_variables = _jinja_variables(original) - _jinja_variables(patched)
    if dropped_variables:
        return DROPPED_VARIABLES_ERROR.format(
            names=", ".join(sorted(dropped_variables))
        )

    dropped_tags = _yaml_tags(original) - _yaml_tags(patched)
    if dropped_tags:
        return DROPPED_TAGS_ERROR.format(tags=", ".join(sorted(dropped_tags)))

    return None
