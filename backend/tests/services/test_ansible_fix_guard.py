"""Tests for the differential guard on Ansible LLM rewrites.

The guard's whole job is to be asymmetric: it must accept everything a real fix
does — adding filters, adding tasks, reordering, re-commenting — while refusing
the two edits that break a deployment without breaking the parse. So the cases
below are weighted towards what must be *accepted*; a guard that rejects real
fixes is worse than no guard, because it fails every generation silently.
"""

import pathlib

import pytest

from app.services.ansible.discovery import classify_ansible_file
from app.services.ansible.fix_guard import (
    DROPPED_TAGS_ERROR,
    DROPPED_VARIABLES_ERROR,
    INVALID_YAML_ERROR,
    validate_ansible_fix,
)

_PATH = "roles/docker/tasks/main.yml"

_UNQUOTED_SHELL = """---
- name: Log in to ECR
  ansible.builtin.shell:
    cmd: docker login -u AWS {{ registry }} --region {{ greensecops_region }}
  changed_when: false
"""

_VAULTED_VARS = """---
database_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  6231623764363464
api_token: plain
"""


def test_identity_is_always_a_valid_rewrite() -> None:
    assert validate_ansible_fix(_PATH, _UNQUOTED_SHELL, _UNQUOTED_SHELL) is None


def test_adding_the_quote_filter_is_accepted() -> None:
    """The exact rewrite ``shell_with_unquoted_variable`` asks for.

    This is the case that rules out comparing raw expression text: the fix
    *changes* every interpolation it touches, and a textual comparison would
    reject the engine's own recommendation.
    """
    patched = _UNQUOTED_SHELL.replace(
        "{{ registry }} --region {{ greensecops_region }}",
        "{{ registry | quote }} --region {{ greensecops_region | quote }}",
    )
    assert validate_ansible_fix(_PATH, _UNQUOTED_SHELL, patched) is None


def test_dropping_a_variable_is_rejected() -> None:
    patched = _UNQUOTED_SHELL.replace(" --region {{ greensecops_region }}", "")
    error = validate_ansible_fix(_PATH, _UNQUOTED_SHELL, patched)
    assert error == DROPPED_VARIABLES_ERROR.format(names="greensecops_region")


def test_renaming_a_variable_is_rejected() -> None:
    # A rename parses and looks tidier, but the name is resolved from inventory
    # or another role's defaults, which the model never saw.
    patched = _UNQUOTED_SHELL.replace("{{ registry }}", "{{ ecr_registry }}")
    error = validate_ansible_fix(_PATH, _UNQUOTED_SHELL, patched)
    assert error == DROPPED_VARIABLES_ERROR.format(names="registry")


def test_adding_a_new_variable_is_accepted() -> None:
    """Containment runs one way only: original ⊆ patched, never equality.

    Pinning a checksum introduces a variable that was not there before, which
    is a fix, not a regression.
    """
    patched = (
        _UNQUOTED_SHELL
        + """
- name: Install the Compose plugin
  ansible.builtin.get_url:
    url: https://example.com/compose
    dest: /usr/libexec/docker/compose
    checksum: "sha256:{{ docker_compose_sha256[docker_compose_arch] }}"
"""
    )
    assert validate_ansible_fix(_PATH, _UNQUOTED_SHELL, patched) is None


def test_adding_a_task_is_accepted() -> None:
    patched = (
        _UNQUOTED_SHELL
        + """
- name: Verify the login
  ansible.builtin.command: docker info
  changed_when: false
"""
    )
    assert validate_ansible_fix(_PATH, _UNQUOTED_SHELL, patched) is None


def test_dropping_a_vault_tag_is_rejected() -> None:
    """The failure this guard exists for.

    Without the tag the file still parses and still classifies as vars — the
    ciphertext is simply a string now, and whatever authenticates with it fails
    at runtime rather than at delivery.
    """
    patched = _VAULTED_VARS.replace("!vault |", "|")
    error = validate_ansible_fix("group_vars/all.yml", _VAULTED_VARS, patched)
    assert error == DROPPED_TAGS_ERROR.format(tags="!vault")


def test_keeping_the_vault_tag_while_editing_elsewhere_is_accepted() -> None:
    patched = _VAULTED_VARS.replace("api_token: plain", "api_token: plain\nextra: 1")
    assert validate_ansible_fix("group_vars/all.yml", _VAULTED_VARS, patched) is None


def test_unparseable_yaml_is_rejected() -> None:
    assert (
        validate_ansible_fix(_PATH, _UNQUOTED_SHELL, "- name: [unclosed\n")
        == INVALID_YAML_ERROR
    )


def test_content_that_is_no_longer_ansible_is_rejected() -> None:
    # Parses fine as YAML; classifies as nothing this engine grades.
    assert (
        validate_ansible_fix(_PATH, _UNQUOTED_SHELL, "just: a mapping\n")
        == INVALID_YAML_ERROR
    )


def test_wrapping_a_task_file_into_a_playbook_is_rejected() -> None:
    """A task file included by ``roles/*/tasks/main.yml`` is not a playbook.

    Wrapping it in a play parses, and each half classifies as a legitimate
    kind — but the include that pulls it in would then fail.
    """
    patched = """---
- name: Wrapped
  hosts: all
  tasks:
    - name: Log in to ECR
      ansible.builtin.shell:
        cmd: docker login -u AWS {{ registry }} --region {{ greensecops_region }}
      changed_when: false
"""
    error = validate_ansible_fix(_PATH, _UNQUOTED_SHELL, patched)
    assert error is not None
    assert "changed the file's kind" in error


def test_a_jinja_filter_name_is_not_treated_as_a_variable() -> None:
    """Dropping a filter is allowed; dropping a variable is not.

    If filters counted as variables, removing a now-redundant ``| default(...)``
    would fail the whole generation.
    """
    original = (
        "- name: t\n  ansible.builtin.debug:\n    msg: {{ value | default('x') }}\n"
    )
    patched = "- name: t\n  ansible.builtin.debug:\n    msg: {{ value }}\n"
    assert validate_ansible_fix(_PATH, original, patched) is None


def test_an_attribute_access_is_not_treated_as_a_variable() -> None:
    original = "- name: t\n  ansible.builtin.debug:\n    msg: {{ result.stdout }}\n"
    patched = (
        "- name: t\n  ansible.builtin.debug:\n    msg: {{ result.stdout_lines }}\n"
    )
    assert validate_ansible_fix(_PATH, original, patched) is None


@pytest.mark.parametrize(
    "path",
    sorted(
        p
        for p in pathlib.Path(__file__).parents[3].joinpath("deploy/ansible").rglob("*")
        if p.suffix in {".yml", ".yaml"}
    ),
    ids=lambda p: str(p.name),
)
def test_the_repos_own_ansible_tree_is_never_falsely_rejected(
    path: pathlib.Path,
) -> None:
    """Every real Ansible file here is a valid rewrite of itself.

    Runs against the deployment tree rather than fixtures because the guard's
    failure mode is over-rejection, and only real files carry the Jinja and
    tagged scalars that provoke it.
    """
    content = path.read_text()
    relative = str(path.relative_to(pathlib.Path(__file__).parents[3]))
    if classify_ansible_file(relative, content) is None:
        pytest.skip("not an Ansible file")
    assert validate_ansible_fix(relative, content, content) is None
