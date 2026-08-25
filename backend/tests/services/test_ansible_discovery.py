"""Ansible file classification.

The point of these tests is the negative half. Ansible has no extension of its
own, so the classifier's job is as much to reject a Compose file or a GitHub
Actions workflow as it is to recognise a playbook — and the cost of a false
positive is a whole foreign file scanned by rules written for something else.
"""

from app.services.ansible.discovery import (
    HANDLERS,
    PLAYBOOK,
    REQUIREMENTS,
    TASKS,
    VARS,
    classify_ansible_file,
    in_skipped_directory,
    is_task_keyword,
)

PLAYBOOK_YAML = """---
- name: Configure the web tier
  hosts: web
  become: true
  tasks:
    - name: Install nginx
      ansible.builtin.apt:
        name: nginx
        state: present
"""

IMPORT_ONLY_PLAYBOOK = """---
- name: Build the images
  ansible.builtin.import_playbook: build.yml
"""

TASKS_YAML = """---
- name: Install nginx
  ansible.builtin.apt:
    name: nginx
    state: present
"""

COMPOSE_YAML = """---
services:
  api:
    image: app:1.0
    ports:
      - "8000:8000"
"""

WORKFLOW_YAML = """---
name: ci
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""


def test_playbook_is_recognised() -> None:
    assert classify_ansible_file("playbooks/site.yml", PLAYBOOK_YAML) == PLAYBOOK


def test_a_playbook_of_imports_is_still_a_playbook() -> None:
    assert classify_ansible_file("site.yml", IMPORT_ONLY_PLAYBOOK) == PLAYBOOK


def test_task_file_is_recognised() -> None:
    assert classify_ansible_file("roles/web/tasks/main.yml", TASKS_YAML) == TASKS


def test_handler_file_is_distinguished_by_path() -> None:
    assert classify_ansible_file("roles/web/handlers/main.yml", TASKS_YAML) == HANDLERS


def test_group_vars_is_a_vars_file() -> None:
    assert classify_ansible_file("group_vars/all.yml", "app_port: 8080\n") == VARS


def test_role_defaults_is_a_vars_file() -> None:
    assert classify_ansible_file("roles/web/defaults/main.yml", "a: 1\n") == VARS


def test_galaxy_requirements_is_recognised() -> None:
    content = "collections:\n  - name: amazon.aws\n"
    assert classify_ansible_file("requirements.yml", content) == REQUIREMENTS


def test_a_python_requirements_file_at_the_same_name_is_not() -> None:
    # A mapping at requirements.yml that names neither collections nor roles is
    # somebody else's file.
    assert classify_ansible_file("requirements.yml", "packages:\n  - httpx\n") is None


def test_compose_file_is_rejected() -> None:
    assert classify_ansible_file("compose.yml", COMPOSE_YAML) is None


def test_github_workflow_is_rejected_by_content() -> None:
    assert classify_ansible_file("ci.yml", WORKFLOW_YAML) is None


def test_github_workflow_directory_is_rejected_outright() -> None:
    # Belt and braces: even Ansible-shaped content under .github is not ours.
    assert classify_ansible_file(".github/workflows/ci.yml", TASKS_YAML) is None


def test_non_yaml_is_rejected() -> None:
    assert classify_ansible_file("roles/web/tasks/main.json", TASKS_YAML) is None


def test_malformed_yaml_is_rejected_rather_than_raising() -> None:
    assert classify_ansible_file("playbooks/site.yml", "- name: [unclosed\n") is None


def test_empty_document_is_rejected() -> None:
    assert classify_ansible_file("playbooks/site.yml", "---\n") is None


def test_vault_tagged_values_do_not_break_classification() -> None:
    content = (
        "- name: Configure\n"
        "  ansible.builtin.debug:\n"
        "    msg: hello\n"
        "  vars:\n"
        "    pw: !vault |\n"
        "      $ANSIBLE_VAULT;1.1;AES256\n"
        "      3132\n"
    )
    assert classify_ansible_file("roles/web/tasks/main.yml", content) == TASKS


def test_a_sequence_of_plain_strings_is_not_a_task_file() -> None:
    assert classify_ansible_file("roles/web/tasks/main.yml", "- one\n- two\n") is None


def test_in_skipped_directory_ignores_the_file_itself() -> None:
    assert in_skipped_directory("node_modules/pkg/playbook.yml")
    assert not in_skipped_directory("roles/web/tasks/main.yml")
    # A file *named* like a skipped directory is not in one.
    assert not in_skipped_directory("build")


def test_with_prefixed_loops_are_task_keywords() -> None:
    assert is_task_keyword("with_items")
    assert is_task_keyword("when")
    assert not is_task_keyword("ansible.builtin.apt")
