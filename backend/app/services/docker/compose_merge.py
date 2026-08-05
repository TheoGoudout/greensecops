"""Apply Compose's own merge rules to a base file and its override.

Compose does not evaluate ``compose.yml`` and ``compose.override.yml``
separately — it merges them at invocation time and runs the result. Evaluating
them as they sit on disk therefore answers a question nobody asked: a setting
the override supplies is reported missing from the base, and a setting the
override *adds* is judged against the base's context.

The workaround for that was ``is_override``, a flag telling absence-based rules
to skip override documents entirely — which traded false positives for silence,
since the base's own gaps then went unreported too whenever an override existed.
This computes the merged configuration instead, so those rules can judge what
Compose will actually run.

**The asymmetry that makes this necessary.** Compose does not merge every field
the same way. Scalars and mappings are replaced or merged key-by-key, but most
*sequences* are appended — an override adding ``cap_add: [SYS_ADMIN]`` does not
replace the base's capabilities, it adds to them. A few sequences are replaced
instead, because appending them would be meaningless (you cannot run two
``command``s). Getting that backwards is exactly how a naive merge produces
wrong answers.

**Not modelled**, and recorded here for the same reason the previous limitation
was:

- ``extends:``. Its ``file:`` key can point at any path, including one
  ``classify_docker_file`` does not recognise, so resolving it needs a second
  fetch pass rather than a merge.
- ``!reset`` and ``!override`` tags, which force replacement over the default
  merge behaviour.
- Profiles, which can exclude a service from the running configuration.
- ``${VAR}`` interpolation and ``env_file`` loading, which change values before
  the merge happens.
"""

import logging
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

# Sequences Compose *replaces* rather than appends. Everything else in a
# service — ports, volumes, cap_add, cap_drop, security_opt, expose, dns,
# tmpfs, devices — is appended, which is why an override cannot be read as the
# whole truth about a service and why absence-based rules needed the merged
# document to be sound.
_REPLACED_SEQUENCE_KEYS = frozenset(
    {
        "command",
        "entrypoint",
        "env_file",
        "healthcheck",  # a mapping, but replaced wholesale rather than merged
    }
)

# Keys the parser injects. They describe one file, so the merged document gets
# its own rather than inheriting whichever file happened to be merged last.
_SOURCE_FILE_KEY = "__docker_file"
_SOURCE_FILES_KEY = "__compose_files"
_START_LINE_KEY = "__start_line__"
_END_LINE_KEY = "__end_line__"
_INTERNAL_KEYS = frozenset(
    {_SOURCE_FILE_KEY, _SOURCE_FILES_KEY, _START_LINE_KEY, _END_LINE_KEY, "is_override"}
)


def _merge_value(key: str, base: Any, override: Any) -> Any:
    """Merge one field the way Compose does."""
    if key in _REPLACED_SEQUENCE_KEYS:
        return override
    if isinstance(base, dict) and isinstance(override, dict):
        return _merge_mappings(base, override)
    if isinstance(base, list) and isinstance(override, list):
        # Appended, not replaced — and de-duplicated, since restating a port
        # or a capability in the override is the common way to make it
        # explicit rather than a request for two of them.
        merged = list(base)
        merged.extend(item for item in override if item not in base)
        return merged
    return override


def _merge_mappings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in _INTERNAL_KEYS:
            continue
        merged[key] = _merge_value(key, base[key], value) if key in base else value
    return merged


def _merge_services(
    base: dict[str, Any],
    override: dict[str, Any],
    base_path: str,
    override_path: str,
) -> dict[str, Any]:
    """Merge the ``services`` mappings of two documents.

    A service the override introduces is carried over whole; one it restates is
    merged field by field, keeping the base's line span because that is where a
    reader would go to see the service defined.

    Each service also carries the path of the file that span belongs to. The
    merged document is named for the base, but a service only the override
    declares is not in the base at all — attributing it there would send a
    reader to a file the service does not appear in, at a line number taken
    from a different file.
    """
    merged: dict[str, Any] = {}
    for name, service in base.items():
        if isinstance(service, dict):
            merged[name] = {**service, _SOURCE_FILE_KEY: base_path}
        else:
            merged[name] = service
    for name, service in override.items():
        existing = merged.get(name)
        if isinstance(existing, dict) and isinstance(service, dict):
            kept = {
                key: existing[key]
                for key in (_START_LINE_KEY, _END_LINE_KEY, _SOURCE_FILE_KEY)
                if key in existing
            }
            merged[name] = {**_merge_mappings(existing, service), **kept}
        elif name not in merged or merged[name] is None:
            merged[name] = (
                {**service, _SOURCE_FILE_KEY: override_path}
                if isinstance(service, dict)
                else service
            )
    return merged


def _override_base_name(path: str) -> str:
    """The base file an override belongs to — same directory, name minus the infix."""
    pure = PurePosixPath(path)
    return str(pure.with_name(pure.name.replace(".override.", ".", 1)))


def effective_compose_documents(
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One document per *configuration* — what Compose would actually run.

    A base file with an override yields their merge; a file without one yields
    itself. This is the list an absence-based rule reads, because absence is
    only meaningful about a complete configuration. Rules that fire on the
    *presence* of something dangerous keep reading ``compose_files`` instead,
    so they report the file that actually contains the offending line rather
    than a merged document that exists nowhere on disk.

    Files are paired by name within a directory (``compose.yml`` with
    ``compose.override.yml``), not by the order they were fetched — the GitHub
    contents API returns a directory listing with no sort, and alphabetically
    the override arrives *first*, which is the opposite of what merging needs.
    """
    by_path = {
        doc.get(_SOURCE_FILE_KEY, ""): doc for doc in documents if isinstance(doc, dict)
    }
    effective: list[dict[str, Any]] = []
    superseded: set[str] = set()

    for path, override in sorted(by_path.items()):
        if not override.get("is_override"):
            continue
        base_path = _override_base_name(path)
        base = by_path.get(base_path)
        if base is None:
            # An override with no base in this target cannot be merged into
            # anything, and on its own it is not a configuration — absence in
            # it says nothing, so it contributes no effective document.
            logger.debug("Compose override %s has no base file in this target", path)
            superseded.add(path)
            continue

        # The generic pass handles the top-level keys — `volumes`, `networks`,
        # `configs`. `services` needs the per-service rules below, so its
        # result here is immediately replaced.
        merged = _merge_mappings(base, override)
        merged["services"] = _merge_services(
            base.get("services") or {},
            override.get("services") or {},
            base_path,
            path,
        )
        merged[_SOURCE_FILE_KEY] = base_path
        merged[_SOURCE_FILES_KEY] = [base_path, path]
        merged["is_override"] = False
        effective.append(merged)
        superseded.update({base_path, path})

    for path, document in sorted(by_path.items()):
        if path not in superseded:
            effective.append(document)

    return effective
