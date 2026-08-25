"""Ansible YAML → JSON document with source line spans, for OPA evaluation.

Parsed in ruamel's **round-trip** mode, the only mode that keeps position data
(``node.lc``), and converted to plain types by ``services/yaml_positions`` —
the same path ``services/docker/compose_parser`` takes. Nothing here re-derives
line numbers from a second parse.

Three things are resolved in Python rather than left to Rego, because each of
them is either impossible or miserable to express in a policy language:

**Blocks are flattened.** Rego forbids recursive rule definitions, so a rule
cannot walk arbitrarily nested ``block``/``rescue``/``always``. The parser emits
one flat task list per file with ``__block_depth__`` recorded, and propagates the
keywords Ansible itself inherits from a block into the children that do not set
them — otherwise a rule would report a task as missing a ``no_log`` its
enclosing block already supplied.

**The module key is resolved.** An Ansible task is a mapping whose *module name
is a key* sitting beside ``name``, ``when``, ``loop`` and the rest, so the module
is whatever is left after removing the keywords. That keyword set is
version-dependent (``discovery.TASK_KEYWORDS``); resolving it once here means a
new Ansible release is one edit rather than one per rule.

**Names are normalised to FQCN.** ``apt``, ``ansible.builtin.apt`` and a
``collections:``-scoped short name are the same module. Rules compare
``__module__`` and never have to carry an alias table.

The document is an **envelope of files** rather than one merged config, because
a task file is not mergeable with a playbook. That shape is also what keeps the
suite safe under ``scripts/validate_examples.py``, which evaluates a GitHub
Actions workflow against every domain's packages: every Ansible rule opens by
iterating ``input.files``, which a workflow document does not have, so the whole
suite is vacuously silent on foreign input.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from app.services.ansible.discovery import (
    HANDLERS,
    PLAYBOOK,
    REQUIREMENTS,
    TASKS,
    VARS,
    classify_ansible_file,
    is_task_keyword,
)
from app.services.yaml_positions import (
    convert_with_positions,
    key_line,
)

logger = logging.getLogger(__name__)

SOURCE_FILE_KEY = "__ansible_file"

#: Where a task was found within its play. Task files report ``tasks``.
SECTION_KEYS = ("pre_tasks", "tasks", "post_tasks", "handlers")

#: Keywords a block passes down to the tasks inside it. Ansible applies these
#: to every child that does not set its own, so a rule that reads them off the
#: flattened task must see the inherited value or it reports a false positive.
_INHERITED_KEYWORDS = (
    "become",
    "become_user",
    "check_mode",
    "environment",
    "ignore_errors",
    "no_log",
    "tags",
    "when",
)

#: Short module names that resolve to ``ansible.builtin``. Not exhaustive —
#: an unknown short name is left as written, since the collection it belongs to
#: cannot be guessed — but it covers the modules the rule suite reasons about.
_BUILTIN_MODULES = frozenset(
    {
        "add_host",
        "apt",
        "apt_key",
        "apt_repository",
        "assemble",
        "assert",
        "async_status",
        "blockinfile",
        "command",
        "copy",
        "cron",
        "debconf",
        "debug",
        "dnf",
        "dpkg_selections",
        "expect",
        "fail",
        "fetch",
        "file",
        "find",
        "gather_facts",
        "get_url",
        "getent",
        "git",
        "group",
        "group_by",
        "hostname",
        "import_playbook",
        "import_role",
        "import_tasks",
        "include_role",
        "include_tasks",
        "include_vars",
        "iptables",
        "known_hosts",
        "lineinfile",
        "meta",
        "mount_facts",
        "package",
        "package_facts",
        "pause",
        "ping",
        "pip",
        "raw",
        "reboot",
        "replace",
        "rpm_key",
        "script",
        "service",
        "service_facts",
        "set_fact",
        "set_stats",
        "setup",
        "shell",
        "slurp",
        "stat",
        "subversion",
        "systemd",
        "systemd_service",
        "sysvinit",
        "tempfile",
        "template",
        "unarchive",
        "uri",
        "user",
        "validate_argument_spec",
        "wait_for",
        "wait_for_connection",
        "yum",
        "yum_repository",
    }
)

#: Modules whose value is conventionally a bare command string. Ansible calls
#: that positional value ``_raw_params``; using the same name means a rule reads
#: ``shell: rm -rf /`` and ``shell: {cmd: rm -rf /}`` the same way.
RAW_PARAMS_KEY = "_raw_params"


def normalize_module(name: str) -> str:
    """The fully-qualified name of a module written any of the legal ways."""
    if "." in name:
        return name
    if name in _BUILTIN_MODULES:
        return f"ansible.builtin.{name}"
    return name


def _module_key(task: dict[str, Any]) -> str | None:
    """The one key naming a module, or ``None`` if it cannot be told.

    Ambiguity is reported rather than guessed: two non-keyword keys means the
    file is not valid Ansible, and inventing a module for it would produce
    findings against something that never runs.
    """
    candidates = [
        key
        for key in task
        if not is_task_keyword(str(key)) and not str(key).startswith("__")
    ]
    if len(candidates) != 1:
        return None
    return str(candidates[0])


def _module_args(value: Any, task: dict[str, Any]) -> dict[str, Any]:
    """A module's arguments, whichever form they were written in.

    A bare string becomes ``{_raw_params: ...}``; a task-level ``args:`` mapping
    is merged in, which is what Ansible does with it.
    """
    if isinstance(value, dict):
        args: dict[str, Any] = dict(value)
    elif value is None:
        args = {}
    else:
        args = {RAW_PARAMS_KEY: value}

    extra = task.get("args")
    if isinstance(extra, dict):
        args.update(extra)
    return args


def _resolve_action(task: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The module named by a free-form ``action:``/``local_action:``, if any.

    The legacy spelling puts the module name in the value rather than in a key
    of its own, so the by-elimination scan above cannot find it.
    """
    action = task.get("action", task.get("local_action"))
    if isinstance(action, str):
        name, _, rest = action.partition(" ")
        args = {RAW_PARAMS_KEY: rest.strip()} if rest.strip() else {}
        return normalize_module(name), args
    if isinstance(action, dict):
        module = action.get("module")
        if isinstance(module, str):
            args = {k: v for k, v in action.items() if k != "module"}
            return normalize_module(module), args
    return None


def _flatten_tasks(
    raw_tasks: Any,
    *,
    section: str,
    play_index: int | None,
    depth: int = 0,
    inherited: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every task in ``raw_tasks``, with blocks flattened into the same list."""
    if not isinstance(raw_tasks, list):
        return []

    flattened: list[dict[str, Any]] = []
    for index, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, dict):
            continue
        start = key_line(raw_tasks, index, 1)

        block = raw_task.get("block")
        if isinstance(block, list):
            # The block itself is a container, not a task: only its children are
            # reported. What it *does* contribute is the keywords its children
            # inherit.
            passed_down = dict(inherited or {})
            for keyword in _INHERITED_KEYWORDS:
                if keyword in raw_task:
                    passed_down[keyword] = raw_task[keyword]
            for key in ("block", "rescue", "always"):
                flattened.extend(
                    _flatten_tasks(
                        raw_task.get(key),
                        section=section,
                        play_index=play_index,
                        depth=depth + 1,
                        inherited=passed_down,
                    )
                )
            continue

        task = _convert_task(
            raw_task,
            start=start,
            section=section,
            play_index=play_index,
            depth=depth,
            inherited=inherited,
        )
        if task is not None:
            flattened.append(task)
    return flattened


def _convert_task(
    raw_task: dict[str, Any],
    *,
    start: int,
    section: str,
    play_index: int | None,
    depth: int,
    inherited: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """One task as a JSON-safe mapping, with its module and span resolved."""
    converted, _, end = convert_with_positions(raw_task, start)
    if not isinstance(converted, dict):
        return None

    # Inherited keywords are filled in only where the task is silent, matching
    # how Ansible resolves them.
    for keyword, value in (inherited or {}).items():
        if keyword not in converted:
            child, _, _ = convert_with_positions(value, start)
            converted[keyword] = child

    key = _module_key(raw_task)
    if key is not None:
        converted["__module__"] = normalize_module(key)
        converted["__args__"] = _module_args(converted.get(key), converted)
    else:
        resolved = _resolve_action(converted)
        if resolved is None:
            return None
        converted["__module__"], converted["__args__"] = resolved

    converted["__section__"] = section
    converted["__block_depth__"] = depth
    converted["__start_line__"] = start
    converted["__end_line__"] = max(end, start)
    if play_index is not None:
        converted["__play_index__"] = play_index
    return converted


def _convert_play(raw_play: dict[str, Any], start: int, index: int) -> dict[str, Any]:
    """A play's own keywords, without the task lists hanging off it.

    Tasks live in the file-level ``tasks`` array instead, each tagged with
    ``__play_index__`` — one place to iterate, whatever the file kind.
    """
    stripped = {k: v for k, v in raw_play.items() if str(k) not in SECTION_KEYS}
    converted, _, end = convert_with_positions(stripped, start)
    play: dict[str, Any] = converted if isinstance(converted, dict) else {}
    play["__play_index__"] = index
    play["__start_line__"] = start
    play["__end_line__"] = max(end, start)
    return play


def _load_documents(path: str, raw_content: str) -> list[Any] | None:
    try:
        loaded = list(YAML(typ="rt").load_all(io.StringIO(raw_content)))
    except YAMLError as exc:
        logger.warning("Failed to parse Ansible file %s: %s", path, exc)
        return None
    return [doc for doc in loaded if doc is not None]


def _parse_playbook(documents: list[Any]) -> dict[str, Any]:
    plays: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    index = 0
    for document in documents:
        if not isinstance(document, list):
            continue
        for position, raw_play in enumerate(document):
            if not isinstance(raw_play, dict):
                continue
            start = key_line(document, position, 1)
            plays.append(_convert_play(raw_play, start, index))
            for section in SECTION_KEYS:
                tasks.extend(
                    _flatten_tasks(
                        raw_play.get(section), section=section, play_index=index
                    )
                )
            index += 1
    return {"plays": plays, "tasks": tasks}


def _parse_task_file(documents: list[Any], section: str) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for document in documents:
        tasks.extend(_flatten_tasks(document, section=section, play_index=None))
    return {"tasks": tasks}


def _parse_mapping(documents: list[Any], key: str) -> dict[str, Any]:
    first = documents[0] if documents else None
    if not isinstance(first, dict):
        return {key: {}}
    converted, _, _ = convert_with_positions(first, 1)
    body: dict[str, Any] = converted if isinstance(converted, dict) else {}
    # Stamp each entry so a finding can point at the offending key rather than
    # at the top of the file. Sequence values — a galaxy file's ``collections:``
    # list — are stamped per element, since that is the granularity a finding
    # about one dependency needs.
    for name in list(body):
        if name.startswith("__"):
            continue
        line = key_line(first, name, 1)
        value = body[name]
        if isinstance(value, dict):
            value["__start_line__"] = line
        elif isinstance(value, list):
            raw_list = first.get(name)
            for index, element in enumerate(value):
                if isinstance(element, dict):
                    element["__start_line__"] = key_line(raw_list, index, line)
            body.setdefault("__lines__", {})[name] = line
        else:
            body.setdefault("__lines__", {})[name] = line
    return {key: body}


def parse_ansible_content(path: str, raw_content: str) -> dict[str, Any] | None:
    """Parse one Ansible file into its OPA document entry.

    Returns ``None`` when the file is not Ansible content or will not parse,
    rather than raising, so one bad file does not abort a scan.
    """
    kind = classify_ansible_file(path, raw_content)
    if kind is None:
        return None
    documents = _load_documents(path, raw_content)
    if not documents:
        return None

    if kind == PLAYBOOK:
        body = _parse_playbook(documents)
    elif kind in (TASKS, HANDLERS):
        body = _parse_task_file(documents, TASKS if kind == TASKS else HANDLERS)
    elif kind == VARS:
        body = _parse_mapping(documents, "vars")
    elif kind == REQUIREMENTS:
        body = _parse_mapping(documents, "requirements")
    else:  # pragma: no cover - KINDS is closed
        return None

    # A per-file ordinal, used only to tell two *unnamed* tasks of the same
    # module apart when a finding is fingerprinted. Named tasks — which is
    # almost all of them — key on their name instead, so the fingerprint
    # survives a task being inserted above them.
    for index, task in enumerate(body.get("tasks", [])):
        task["__task_index__"] = index

    return {SOURCE_FILE_KEY: path, "kind": kind, **body}


def merge_ansible_files(files: list[tuple[str, str]]) -> dict[str, Any]:
    """Build the OPA input document from a project's fetched files.

    Files that are not Ansible content, or that will not parse, are dropped —
    the same contract the Docker and Terraform mergers keep.
    """
    entries = []
    for path, content in files:
        entry = parse_ansible_content(path, content)
        if entry is not None:
            entries.append(entry)
    return {"files": entries}
