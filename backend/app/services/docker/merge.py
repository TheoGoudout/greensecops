"""Merge a target's Docker files into the single document OPA evaluates.

Mirrors ``services/terraform/hcl_parser.merge_terraform_configs``: one scan per
target, not per file. Unlike Terraform — where merging is *semantically*
required because a resource in one file references a variable in another —
Docker files are independent, and the merge here exists so that rules can
correlate across them: a Compose service's ``build.dockerfile`` points at a
Dockerfile in the same target, and a rule that wants to say "this service runs
a root container" needs both documents in one input.

Two lists come out of it, because a Compose target answers two different
questions. ``compose_files`` is the files as they sit on disk, which is what a
rule firing on the *presence* of something dangerous must report — the line is
in one of them. ``effective_compose_files`` is one document per configuration,
with a base and its override merged the way Compose merges them (see
``compose_merge``), which is what a rule firing on the *absence* of a setting
must read, since absence is only meaningful about a complete configuration.

``extends:`` is still not resolved — its ``file:`` key can point at a path the
fetcher never collected, so it needs a second fetch pass rather than a merge.
That remains the same class of documented approximation as
``hcl_parser.derive_module_path`` being a directory heuristic rather than
resolved ``module {}`` invocation — honest and stable, not complete.

``--target`` builds are likewise not modelled: the final stage is taken to be
the last ``FROM``, which is what ``docker build`` produces by default.
"""

import logging
from pathlib import PurePosixPath
from typing import Any

from .compose_merge import effective_compose_documents
from .compose_parser import parse_compose_content
from .dockerfile_parser import parse_dockerfile_content

logger = logging.getLogger(__name__)

DOCKERFILE = "dockerfile"
COMPOSE = "compose"

_DOCKERFILE_STEMS = {"dockerfile", "containerfile"}
_COMPOSE_STEMS = {"compose", "docker-compose"}
_YAML_SUFFIXES = {".yml", ".yaml"}

# ``Dockerfile.md`` is documentation about a Dockerfile, not one. Anything
# whose trailing suffix is a known document/lockfile type is not a build file
# however much its stem looks like one.
_NOT_A_DOCKERFILE_SUFFIX = {
    ".md",
    ".txt",
    ".rst",
    ".lock",
    ".log",
    ".json",
    ".yml",
    ".yaml",
}


def classify_docker_file(path: str) -> str | None:
    """Return ``DOCKERFILE``, ``COMPOSE``, or ``None`` for a repository path.

    Recognises ``Dockerfile``, ``Dockerfile.prod``, ``prod.Dockerfile``,
    ``Containerfile``, ``compose.yml``, ``compose.override.yaml`` and
    ``docker-compose.test.yml``. Matching is case-insensitive on the filename
    only — the directory is irrelevant, since a target is scanned recursively.
    """
    name = PurePosixPath(path).name
    if not name:
        return None
    lowered = name.lower()

    if lowered.endswith(".dockerfile"):
        return DOCKERFILE

    head, dot, tail = lowered.partition(".")
    if head in _DOCKERFILE_STEMS:
        if dot and f".{tail.rsplit('.', 1)[-1]}" in _NOT_A_DOCKERFILE_SUFFIX:
            return None
        return DOCKERFILE

    if head in _COMPOSE_STEMS and dot:
        suffix = f".{tail.rsplit('.', 1)[-1]}"
        if suffix in _YAML_SUFFIXES:
            return COMPOSE

    return None


def is_override_file(path: str) -> bool:
    """True for a Compose *override* fragment (``compose.override.yml``).

    An override is not a standalone configuration: Compose auto-loads it on
    top of the base file, and a service listed in it inherits everything it
    doesn't restate. That is what makes it a *fragment*, and the flag is how
    ``compose_merge`` knows which document to fold into which — the merged
    result is what absence-based rules read, so that a setting the override
    supplies is no longer reported missing from the base.

    Deliberately narrow: only the literal ``.override.`` infix qualifies,
    because that is the one filename Compose loads automatically and therefore
    the only one guaranteed to be a fragment. ``compose.prod.yml`` is passed
    explicitly with ``-f`` and may be either a fragment or a complete config,
    so it is treated as complete.
    """
    name = PurePosixPath(path).name.lower()
    return classify_docker_file(path) == COMPOSE and ".override." in name


def merge_docker_files(files: list[tuple[str, str]]) -> dict[str, list[Any]]:
    """Build the OPA input document from ``(path, content)`` pairs.

    Takes plain tuples rather than a fetch-layer type so this stays decoupled
    from ``GitHubAppClient`` — same rationale as ``merge_terraform_configs``.
    Files that fail to parse are skipped with a warning rather than aborting
    the scan; unrecognised filenames are ignored entirely.

    See the module docstring for why ``compose_files`` and
    ``effective_compose_files`` are both returned.
    """
    dockerfiles: list[Any] = []
    compose_files: list[Any] = []

    for path, content in files:
        kind = classify_docker_file(path)
        if kind == DOCKERFILE:
            parsed = parse_dockerfile_content(path, content)
            if parsed is not None:
                dockerfiles.append(parsed)
        elif kind == COMPOSE:
            parsed = parse_compose_content(path, content)
            if parsed is not None:
                # Rules read this to decide whether absence of a setting means
                # anything in this document. See ``is_override_file``.
                parsed["is_override"] = is_override_file(path)
                compose_files.append(parsed)
        else:
            logger.debug("Ignoring non-Docker file %s", path)

    return {
        "dockerfiles": dockerfiles,
        "compose_files": compose_files,
        "effective_compose_files": effective_compose_documents(compose_files),
    }
