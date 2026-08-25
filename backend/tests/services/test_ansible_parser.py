"""Ansible parsing: the OPA document, and the three things resolved in Python.

Block flattening, module resolution and FQCN normalisation are done here rather
than in Rego (Rego forbids recursive rules, and the task-keyword set is
version-dependent), so this is where they have to be pinned down.
"""

from pathlib import Path

from app.services.ansible.parser import (
    SOURCE_FILE_KEY,
    merge_ansible_files,
    normalize_module,
    parse_ansible_content,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PLAYBOOK = """---
- name: Configure the web tier
  hosts: web
  gather_facts: true
  pre_tasks:
    - name: Wait for cloud-init
      ansible.builtin.wait_for:
        path: /etc/ready
  tasks:
    - name: Install nginx
      apt:
        name: nginx
        state: present
  handlers:
    - name: Restart nginx
      ansible.builtin.systemd_service:
        name: nginx
        state: restarted
"""

BLOCKS = """---
- name: Fetch the secrets
  block:
    - name: Read the parameter
      ansible.builtin.command: aws ssm get-parameter
      changed_when: false
    - name: Nested further
      block:
        - name: Deepest task
          ansible.builtin.debug:
            msg: hello
  become: true
  no_log: true
"""


def test_playbook_yields_plays_and_a_flat_task_list() -> None:
    doc = parse_ansible_content("playbooks/site.yml", PLAYBOOK)
    assert doc is not None
    assert doc["kind"] == "playbook"
    assert doc[SOURCE_FILE_KEY] == "playbooks/site.yml"
    assert len(doc["plays"]) == 1
    # pre_tasks, tasks and handlers all land in one array, each tagged with the
    # section it came from — one place for a rule to iterate.
    assert [t["__section__"] for t in doc["tasks"]] == [
        "pre_tasks",
        "tasks",
        "handlers",
    ]


def test_plays_do_not_carry_their_task_lists() -> None:
    doc = parse_ansible_content("playbooks/site.yml", PLAYBOOK)
    assert doc is not None
    play = doc["plays"][0]
    assert play["hosts"] == "web"
    for section in ("tasks", "pre_tasks", "handlers"):
        assert section not in play


def test_short_module_names_are_normalised_to_fqcn() -> None:
    doc = parse_ansible_content("playbooks/site.yml", PLAYBOOK)
    assert doc is not None
    modules = [t["__module__"] for t in doc["tasks"]]
    assert "ansible.builtin.apt" in modules


def test_normalize_module_leaves_unknown_short_names_alone() -> None:
    # The collection cannot be guessed, and inventing one would be worse than
    # leaving the name as written.
    assert normalize_module("apt") == "ansible.builtin.apt"
    assert normalize_module("community.docker.docker_container") == (
        "community.docker.docker_container"
    )
    assert normalize_module("some_unknown_module") == "some_unknown_module"


def test_blocks_are_flattened_with_depth_recorded() -> None:
    doc = parse_ansible_content("roles/x/tasks/main.yml", BLOCKS)
    assert doc is not None
    names = [t["name"] for t in doc["tasks"]]
    # The block containers themselves are not tasks; only their children are —
    # and "Nested further" is a container too, so it does not appear either.
    assert names == ["Read the parameter", "Deepest task"]
    depths = {t["name"]: t["__block_depth__"] for t in doc["tasks"]}
    assert depths["Read the parameter"] == 1
    assert depths["Deepest task"] == 2


def test_block_keywords_are_inherited_by_the_tasks_inside() -> None:
    doc = parse_ansible_content("roles/x/tasks/main.yml", BLOCKS)
    assert doc is not None
    # Ansible applies a block's no_log/become to every child that does not set
    # its own, so a rule reading them off the flattened task must see them.
    assert all(t.get("no_log") is True for t in doc["tasks"])
    assert all(t.get("become") is True for t in doc["tasks"])


def test_a_child_keeps_its_own_value_over_the_blocks() -> None:
    content = (
        "- name: Outer\n"
        "  block:\n"
        "    - name: Inner\n"
        "      ansible.builtin.debug:\n"
        "        msg: hi\n"
        "      no_log: false\n"
        "  no_log: true\n"
    )
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    assert doc["tasks"][0]["no_log"] is False


def test_a_bare_string_module_value_becomes_raw_params() -> None:
    content = "- name: Reload\n  ansible.builtin.command: /usr/sbin/firewall reload\n"
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    assert doc["tasks"][0]["__args__"] == {"_raw_params": "/usr/sbin/firewall reload"}


def test_task_level_args_are_merged_into_module_arguments() -> None:
    content = (
        "- name: Run it\n"
        "  ansible.builtin.command: make\n"
        "  args:\n"
        "    chdir: /src\n"
        "    creates: /src/out\n"
    )
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    args = doc["tasks"][0]["__args__"]
    assert args["chdir"] == "/src"
    assert args["creates"] == "/src/out"
    assert args["_raw_params"] == "make"


def test_line_spans_point_at_the_task() -> None:
    doc = parse_ansible_content("playbooks/site.yml", PLAYBOOK)
    assert doc is not None
    first = doc["tasks"][0]
    assert first["__start_line__"] == 6  # the pre_tasks entry
    assert first["__end_line__"] >= first["__start_line__"]


def test_task_index_is_per_file_and_monotonic() -> None:
    doc = parse_ansible_content("playbooks/site.yml", PLAYBOOK)
    assert doc is not None
    assert [t["__task_index__"] for t in doc["tasks"]] == [0, 1, 2]


def test_requirements_entries_get_their_own_lines() -> None:
    content = "---\ncollections:\n  - name: amazon.aws\n  - name: community.docker\n"
    doc = parse_ansible_content("requirements.yml", content)
    assert doc is not None
    entries = doc["requirements"]["collections"]
    assert entries[0]["__start_line__"] == 3
    assert entries[1]["__start_line__"] == 4


def test_vars_scalars_record_their_line() -> None:
    doc = parse_ansible_content("group_vars/all.yml", "---\na: 1\nb: two\n")
    assert doc is not None
    assert doc["vars"]["__lines__"] == {"a": 2, "b": 3}


def test_vault_tagged_values_are_stringified_rather_than_crashing() -> None:
    content = (
        "- name: Configure\n"
        "  ansible.builtin.debug:\n"
        "    msg: hello\n"
        "  vars:\n"
        "    pw: !vault |\n"
        "      $ANSIBLE_VAULT;1.1;AES256\n"
        "      3132\n"
    )
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    assert isinstance(doc["tasks"][0]["vars"]["pw"], str)


def test_multi_document_files_are_all_parsed() -> None:
    content = "---\n- name: A\n  hosts: a\n---\n- name: B\n  hosts: b\n"
    doc = parse_ansible_content("playbooks/site.yml", content)
    assert doc is not None
    assert [p["name"] for p in doc["plays"]] == ["A", "B"]


def test_a_non_ansible_file_parses_to_nothing() -> None:
    assert (
        parse_ansible_content("compose.yml", "services:\n  api:\n    image: x\n")
        is None
    )


def test_merge_drops_files_that_are_not_ansible() -> None:
    document = merge_ansible_files(
        [
            ("playbooks/site.yml", PLAYBOOK),
            ("compose.yml", "services:\n  api:\n    image: x\n"),
            ("broken.yml", "- name: [unclosed\n"),
        ]
    )
    assert [f[SOURCE_FILE_KEY] for f in document["files"]] == ["playbooks/site.yml"]


def test_the_repositorys_own_deployment_tree_parses() -> None:
    """The end-to-end shape check, against real content rather than fixtures."""
    root = REPO_ROOT / "deploy" / "ansible"
    files = [
        (str(p.relative_to(REPO_ROOT)), p.read_text(encoding="utf-8"))
        for p in sorted(root.rglob("*.yml"))
    ]
    document = merge_ansible_files(files)
    kinds = {f[SOURCE_FILE_KEY]: f["kind"] for f in document["files"]}
    assert kinds["deploy/ansible/playbooks/deploy.yml"] == "playbook"
    assert kinds["deploy/ansible/roles/common/tasks/main.yml"] == "tasks"
    assert kinds["deploy/ansible/roles/docker/handlers/main.yml"] == "handlers"
    assert kinds["deploy/ansible/group_vars/all.yml"] == "vars"
    assert kinds["deploy/ansible/requirements.yml"] == "requirements"
    # The dynamic inventory is YAML in the same tree and must not be picked up.
    assert "deploy/ansible/inventory/aws_ec2.yml" not in kinds


def test_the_action_keyword_in_string_form_resolves_a_module() -> None:
    content = "- name: Ping\n  action: ping\n"
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    assert doc["tasks"][0]["__module__"] == "ansible.builtin.ping"


def test_the_action_keyword_carries_its_positional_argument() -> None:
    content = "- name: Reload\n  action: command /usr/sbin/firewall reload\n"
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    task = doc["tasks"][0]
    assert task["__module__"] == "ansible.builtin.command"
    assert task["__args__"] == {"_raw_params": "/usr/sbin/firewall reload"}


def test_the_action_keyword_in_mapping_form_resolves_a_module() -> None:
    content = "- name: Install\n  action:\n    module: apt\n    name: nginx\n"
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    task = doc["tasks"][0]
    assert task["__module__"] == "ansible.builtin.apt"
    assert task["__args__"] == {"name": "nginx"}


def test_a_task_with_two_candidate_module_keys_is_dropped() -> None:
    # Two non-keyword keys is not valid Ansible. Guessing which one is the
    # module would produce findings against something that never runs.
    content = (
        "- name: Ambiguous\n"
        "  ansible.builtin.apt:\n"
        "    name: nginx\n"
        "  ansible.builtin.dnf:\n"
        "    name: nginx\n"
    )
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    assert doc["tasks"] == []


def test_a_module_invoked_with_no_arguments_yields_empty_args() -> None:
    content = "- name: Ping\n  ansible.builtin.ping:\n"
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    assert doc is not None
    assert doc["tasks"][0]["__args__"] == {}


def test_non_mapping_entries_in_a_task_list_are_skipped() -> None:
    content = "- name: Real\n  ansible.builtin.ping:\n- just a string\n"
    doc = parse_ansible_content("roles/x/tasks/main.yml", content)
    # The sequence is not uniformly task-shaped, so it is not Ansible at all.
    assert doc is None


def test_a_vars_file_whose_document_is_not_a_mapping_yields_an_empty_body() -> None:
    doc = parse_ansible_content("group_vars/all.yml", "- one\n- two\n")
    # Shape wins over path: a sequence under group_vars is not a vars file.
    assert doc is None


def test_a_playbook_entry_that_is_not_a_mapping_is_skipped() -> None:
    content = "- name: Real play\n  hosts: web\n  tasks: []\n"
    doc = parse_ansible_content("playbooks/site.yml", content)
    assert doc is not None
    assert len(doc["plays"]) == 1
    assert doc["tasks"] == []
