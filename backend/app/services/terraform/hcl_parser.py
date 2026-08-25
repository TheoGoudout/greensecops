import json
import logging
from pathlib import PurePosixPath
from typing import Any

import hcl2
from lark.exceptions import LarkError

logger = logging.getLogger(__name__)

# Injected into each named block's attribute dict during merge so a Rego rule
# can report which file a violating resource/data/variable/etc. came from.
# Leading double-underscore mirrors Terraform's own convention for meta
# arguments (``__count__``, ``__index__`` in older internal representations)
# and can't collide with a real HCL identifier, which can't start with digits
# but *can* start with underscores — collision is astronomically unlikely in
# practice, not structurally impossible, so this stays a documented tradeoff.
_SOURCE_FILE_KEY = "__tf_file"


def parse_terraform_content(path: str, raw_content: str) -> dict[str, Any] | None:
    """Parse one ``.tf``/``.tf.json`` file's content to its dict representation.

    Returns ``None`` (rather than raising) on a parse error so one malformed
    file in a root doesn't abort the whole scan — mirrors
    ``opa.evaluator.parse_workflow_yaml`` returning ``None`` on bad YAML.
    """
    try:
        if path.endswith(".json"):
            # JSON Terraform configuration carries no source-line metadata, so
            # ``__start_line__``/``__end_line__`` stay absent and findings from
            # these files keep ``line_start``/``line_end`` null (allowed).
            parsed = json.loads(raw_content)
        else:
            # ``with_meta=True`` stamps ``__start_line__``/``__end_line__`` onto
            # every block's innermost attrs dict (and nested blocks), riding
            # alongside the ``__tf_file`` tag ``merge_terraform_configs`` injects
            # so a Rego rule can report the exact source span of a violation.
            parsed = hcl2.loads(raw_content, with_meta=True)
    except (LarkError, json.JSONDecodeError) as exc:
        logger.warning("Failed to parse Terraform file %s: %s", path, exc)
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


# resource/data entries nest one level deeper than every other top-level
# block type: {type: {name: {attrs}}} vs. variable/output/locals/module/
# provider's {name: {attrs}}. Confirmed empirically against hcl2's actual
# output (a variable_missing_description test initially came back with an
# empty file_path because this distinction was missed on the first pass).
_TWO_LEVEL_BLOCK_TYPES = {"resource", "data"}

# ``terraform`` is the one block type that is *unnamed*: its entry is the attrs
# dict itself, not a {name: attrs} mapping. Walking into its values therefore
# stamps nothing (they are a version string and a nested list), which left
# every finding about a backend or a provider constraint with no file to point
# at. Stamped at the top level instead. ``locals`` is deliberately not treated
# this way — its keys are user-chosen names, so stamping it would invent a
# local called ``__tf_file``.
_SINGLE_LEVEL_BLOCK_TYPES = {"terraform"}


def _tag_source_file(top_level_key: str, block: Any, file_path: str) -> None:
    """Tag every attrs dict in a top-level block entry with its source file.

    Walks in to the innermost attrs dict(s) and stamps them so
    ``merge_terraform_configs`` can attribute a later Rego violation back to
    the file it came from.
    """
    if not isinstance(block, dict):
        return
    if top_level_key in _SINGLE_LEVEL_BLOCK_TYPES:
        block[_SOURCE_FILE_KEY] = file_path
    elif top_level_key in _TWO_LEVEL_BLOCK_TYPES:
        for name_map in block.values():
            if not isinstance(name_map, dict):
                continue
            for attrs in name_map.values():
                if isinstance(attrs, dict):
                    attrs[_SOURCE_FILE_KEY] = file_path
    else:
        for attrs in block.values():
            if isinstance(attrs, dict):
                attrs[_SOURCE_FILE_KEY] = file_path


def merge_terraform_configs(files: list[tuple[str, str]]) -> dict[str, list[Any]]:
    """Merge every file's parsed content into one root-module config.

    Terraform treats every ``.tf``/``.tf.json`` file in a directory as one
    logical module — a resource in one file can reference a variable
    declared in another, so evaluating files independently would produce
    false-positive "undefined reference" style findings. This mirrors that
    by list-concatenating each top-level block type (``resource``,
    ``variable``, ``data``, ...) across every file into one merged document,
    which is what gets fed to OPA as a single input — one ``TerraformScan``
    per root, not per file (unlike the CI-workflow engine, which scans one
    ``WorkflowScan`` per workflow file).

    ``files`` is a list of ``(path, content)`` pairs, not a fetch-layer type,
    so this stays decoupled from ``GitHubAppClient``.
    """
    merged: dict[str, list[Any]] = {}
    for path, content in files:
        parsed = parse_terraform_content(path, content)
        if parsed is None:
            continue
        for key, value in parsed.items():
            block_list = value if isinstance(value, list) else [value]
            for block in block_list:
                _tag_source_file(key, block, path)
            merged.setdefault(key, []).extend(block_list)
    return merged


def derive_module_path(file_path: str, root_path: str) -> str | None:
    """Best-effort module path for a finding, from its file's directory.

    The recursive fetcher merges every ``.tf`` file under a root — including
    files in submodule subdirectories — into one logical config, so a finding's
    ``file_path`` is the only signal of which sub-tree it lives in. This returns
    that file's directory *relative to the root* (posix), or ``None`` when the
    file sits directly in the root (a root-module resource, no module prefix).

    This is a directory-derived heuristic, **not** ``module { source = ... }``
    invocation-name resolution: a module block declared ``module "vpc"`` whose
    source is ``./modules/network`` yields ``modules/network`` here, not
    ``vpc``. Resolving the invocation graph is deliberately out of scope; the
    directory path is a stable, honest locator that always matches the file the
    finding points at.
    """
    file = PurePosixPath(file_path)
    root = PurePosixPath(root_path) if root_path not in ("", ".") else None
    parent = file.parent
    if root is not None:
        try:
            parent = parent.relative_to(root)
        except ValueError:
            # file_path isn't under root_path (shouldn't happen); fall back to
            # the file's own parent directory unchanged.
            pass
    rel = parent.as_posix()
    if rel in ("", "."):
        return None
    return rel
