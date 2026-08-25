#!/usr/bin/env python3
"""Collect a directory's Ansible files and evaluate them against `iac_ansible`.

The Ansible counterpart to ``opa_terraform_eval.py``. Both example validation
(``validate_ansible_examples.py``) and the self-scan of this repository's own
deployment (``validate_deploy_ansible.py``) go through here, so neither can
drift on how a project is collected, parsed or queried.

The parse and merge reuse production's own
``app.services.ansible.parser.merge_ansible_files``, exactly as the Terraform
checker reuses ``merge_terraform_configs``. A checker that parsed differently
from the scanner would validate rules against a document the product never
builds.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from opa_eval import ROOT, domain_query, run_opa_eval

sys.path.insert(0, str(ROOT / "backend"))

from app.services.ansible.discovery import (  # noqa: E402
    classify_ansible_file,
    in_skipped_directory,
)
from app.services.ansible.parser import merge_ansible_files  # noqa: E402

ANSIBLE_VIOLATIONS_QUERY = domain_query("iac_ansible")

_YAML_SUFFIXES = (".yml", ".yaml")


def collect_ansible_files(
    directory: Path, *, recursive: bool = True
) -> list[tuple[str, str]]:
    """Every Ansible file under ``directory``, as ``(relative path, content)``.

    Classification is the production one, so a file this returns is exactly a
    file a scan would fetch.
    """
    pattern = "**/*" if recursive else "*"
    collected: list[tuple[str, str]] = []
    for path in sorted(directory.glob(pattern)):
        if not path.is_file() or path.suffix.lower() not in _YAML_SUFFIXES:
            continue
        relative = path.relative_to(directory).as_posix()
        if in_skipped_directory(relative):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if classify_ansible_file(relative, content) is not None:
            collected.append((relative, content))
    return collected


def evaluate_violations(files: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Every `iac_ansible` violation the files trip."""
    document = merge_ansible_files(files)
    return run_opa_eval(document, ANSIBLE_VIOLATIONS_QUERY)
