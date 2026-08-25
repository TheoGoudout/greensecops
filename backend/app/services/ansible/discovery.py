"""Decide whether a repository file is Ansible content, and of which kind.

Ansible has no file extension of its own and no marker line. A playbook, a
Compose file and a GitHub Actions workflow are all ``.yml``, so the classifier
reads the document's **shape** rather than trusting its path. That is what stops
``compose.yml`` and ``.github/workflows/*.yml`` from being scanned by Ansible
rules — verified against this repository's own trees.

Path is consulted only for the two kinds shape cannot distinguish: a
``requirements.yml`` and a variables file are both plain mappings, and nothing
in the document says which.

Both the fetcher (``GitHubAppClient.fetch_ansible_files``) and the scanner call
:func:`classify_ansible_file`, so the two can never disagree about what an
Ansible file is — a mismatch would silently drop files from a scan. Compare
``services/docker/merge.py::classify_docker_file``, which exists for the same
reason.
"""

from __future__ import annotations

import io
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

PLAYBOOK = "playbook"
TASKS = "tasks"
HANDLERS = "handlers"
VARS = "vars"
REQUIREMENTS = "requirements"

#: Every kind the parser knows how to turn into an OPA document.
KINDS = frozenset({PLAYBOOK, TASKS, HANDLERS, VARS, REQUIREMENTS})

_YAML_SUFFIXES = (".yml", ".yaml")

#: Directories that never hold Ansible content, whatever the shape inside.
#: ``.github`` is the load-bearing one: a workflow's ``jobs:`` mapping is not
#: task-shaped, but excluding the directory outright means a future workflow
#: syntax cannot start tripping Ansible rules.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".github",
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".venv",
        "site-packages",
    }
)

#: Keys that mark a sequence entry as a *play* rather than a task. ``hosts`` is
#: the usual one; the import forms are how a site.yml that contains nothing else
#: still reads as a playbook.
_PLAY_KEYS = frozenset(
    {
        "hosts",
        "import_playbook",
        "ansible.builtin.import_playbook",
        "include_playbook",
    }
)

#: Task keywords — everything that may sit beside the module key in a task
#: mapping. Anything left over after removing these is the module.
#:
#: Kept here rather than in Rego because it is version-dependent: Ansible adds
#: keywords between releases, and a single Python constant is one edit rather
#: than one per rule. ``with_*`` is matched by prefix, not listed.
TASK_KEYWORDS = frozenset(
    {
        "action",
        "always",
        "any_errors_fatal",
        "args",
        "async",
        "become",
        "become_exe",
        "become_flags",
        "become_method",
        "become_user",
        "block",
        "changed_when",
        "check_mode",
        "collections",
        "connection",
        "debugger",
        "delay",
        "delegate_facts",
        "delegate_to",
        "diff",
        "environment",
        "failed_when",
        "ignore_errors",
        "ignore_unreachable",
        "listen",
        "local_action",
        "loop",
        "loop_control",
        "module_defaults",
        "name",
        "no_log",
        "notify",
        "poll",
        "port",
        "register",
        "remote_user",
        "rescue",
        "retries",
        "run_once",
        "tags",
        "throttle",
        "timeout",
        "until",
        "vars",
        "when",
    }
)

#: Play keywords, used to tell a play mapping from a task mapping when the play
#: carries no ``hosts`` (rare, but ``import_playbook`` entries do).
PLAY_KEYWORDS = frozenset(
    {
        "any_errors_fatal",
        "become",
        "become_method",
        "become_user",
        "collections",
        "connection",
        "diff",
        "environment",
        "fact_path",
        "force_handlers",
        "gather_facts",
        "gather_subset",
        "gather_timeout",
        "handlers",
        "hosts",
        "ignore_errors",
        "ignore_unreachable",
        "max_fail_percentage",
        "module_defaults",
        "name",
        "no_log",
        "order",
        "post_tasks",
        "pre_tasks",
        "remote_user",
        "roles",
        "serial",
        "strategy",
        "tags",
        "tasks",
        "throttle",
        "timeout",
        "vars",
        "vars_files",
        "vars_prompt",
    }
)


def is_task_keyword(key: str) -> bool:
    """Whether ``key`` is a task keyword rather than a module name."""
    return key in TASK_KEYWORDS or key.startswith("with_")


def _load_documents(raw_content: str) -> list[Any] | None:
    """Every YAML document in ``raw_content``, or ``None`` if it will not parse.

    Round-trip mode, because the parser downstream needs the position data and
    both must agree on what parsed. Unknown tags (``!vault``) survive as
    ``TaggedScalar`` rather than raising.
    """
    try:
        return list(YAML(typ="rt").load_all(io.StringIO(raw_content)))
    except YAMLError:
        return None


def _is_task_sequence(document: Any) -> bool:
    """Whether ``document`` is a non-empty sequence of task-shaped mappings."""
    if not isinstance(document, list) or not document:
        return False
    for entry in document:
        if not isinstance(entry, dict):
            return False
        keys = {str(k) for k in entry}
        # A task needs at least one key that is not a keyword: the module. A
        # ``block`` counts, since block/rescue/always carry the tasks instead,
        # and so does the legacy free-form ``action``/``local_action``, whose
        # module name sits in the *value* rather than in a key of its own.
        if keys & {"block", "rescue", "always", "action", "local_action"}:
            continue
        if not {k for k in keys if not is_task_keyword(k)}:
            return False
    return True


def _is_play_sequence(document: Any) -> bool:
    """Whether ``document`` is a non-empty sequence of play-shaped mappings."""
    if not isinstance(document, list) or not document:
        return False
    return any(
        isinstance(entry, dict) and ({str(k) for k in entry} & _PLAY_KEYS)
        for entry in document
    )


def _path_segments(path: str) -> list[str]:
    return [segment for segment in path.replace("\\", "/").split("/") if segment]


def in_skipped_directory(path: str) -> bool:
    """Whether ``path`` lies under a directory that never holds Ansible content."""
    segments = _path_segments(path)
    return any(segment in SKIP_DIRS for segment in segments[:-1])


def _kind_from_path(path: str) -> str | None:
    """The kind a path implies, for the kinds shape cannot distinguish."""
    segments = _path_segments(path)
    if not segments:
        return None
    name = segments[-1]
    parents = segments[:-1]

    if name in ("requirements.yml", "requirements.yaml"):
        return REQUIREMENTS
    if {"group_vars", "host_vars"} & set(parents):
        return VARS
    # roles/<role>/{vars,defaults}/main.yml
    if parents and parents[-1] in ("vars", "defaults"):
        return VARS
    if parents and parents[-1] == "handlers":
        return HANDLERS
    return None


def classify_ansible_file(path: str, content: str) -> str | None:
    """Which kind of Ansible file ``path`` is, or ``None`` if it is not one.

    ``content`` is required: the decision is made on the document's shape, and
    a path alone cannot tell a playbook from a Compose file.
    """
    if not path.lower().endswith(_YAML_SUFFIXES):
        return None
    if in_skipped_directory(path):
        return None

    documents = _load_documents(content)
    if documents is None:
        return None
    documents = [doc for doc in documents if doc is not None]
    if not documents:
        return None

    path_kind = _kind_from_path(path)

    if path_kind == REQUIREMENTS:
        # Only a mapping with ``collections``/``roles`` is a galaxy file; a
        # repository may well keep a Python requirements list at that name.
        if isinstance(documents[0], dict) and (
            {"collections", "roles"} & {str(k) for k in documents[0]}
        ):
            return REQUIREMENTS
        return None

    if any(_is_play_sequence(doc) for doc in documents):
        return PLAYBOOK
    if all(_is_task_sequence(doc) for doc in documents):
        return HANDLERS if path_kind == HANDLERS else TASKS
    if path_kind == VARS and isinstance(documents[0], dict):
        return VARS
    return None
