# Ansible examples

Realistic playbooks and role trees used to prove the `iac_ansible` OPA rules
fire (and stay quiet) on real-world content — the Ansible counterpart to
[`examples/terraform/`](../terraform/README.md) and
[`examples/docker/`](../docker/README.md).

Each case is collected and parsed exactly as production does
(`backend/app/services/ansible/discovery.py::classify_ansible_file` and
`backend/app/services/ansible/parser.py::merge_ansible_files`) and evaluated
against the live rule suite by
[`scripts/validate_ansible_examples.py`](../../scripts/validate_ansible_examples.py),
which runs in CI (`.github/workflows/opa.yml`). The set of rules a case trips
must match its `expected.yaml` **exactly**, so a rule that regresses (stops
firing) or starts producing a false positive fails the build.

## The cases

| Case | What it is for |
| --- | --- |
| `web-role-insecure/` | A first-pass role: unpinned packages installed in a loop, an unverified download, a world-writable entrypoint, a token passed in the clear, a shell command interpolating a variable unquoted. Trips 14 of the 16 rules. |
| `web-role-hardened/` | The same role, fixed. Must trip **nothing**. |
| `project-metadata-unpinned/` | Project metadata rather than tasks: a galaxy file with one dependency pinned and one not, and a `group_vars` file carrying one committed credential. |

The clean case matters as much as the bad one. A rule that fires on
`web-role-hardened/` is producing noise on content that is already correct, and
the build fails for it.

`project-metadata-unpinned/` carries one trap deliberately. Its `group_vars`
defines `required_secrets` — a **list of secret names**, not values. A rule keyed
on "this variable is named like a secret" reports it, which is why
`hardcoded_secret_in_vars` requires the value to be a non-templated literal that
also looks like a credential. Only `postgres_password` may be reported there.

## What a case may contain

Files are classified by **shape**, not by path, so a case is laid out the way a
real repository would be:

- a playbook (a sequence of plays)
- `roles/<name>/tasks/main.yml`, `roles/<name>/handlers/main.yml`
- `group_vars/`, `host_vars/`, `roles/<name>/{vars,defaults}/main.yml`
- `requirements.yml` (a mapping with `collections:` or `roles:`)

Anything that is not Ansible-shaped is ignored rather than misread — a Compose
file or a GitHub Actions workflow dropped into a case contributes nothing.

## Adding a new example (no code required)

1. Create a folder here, named for the scenario (e.g. `vault-usage/`).
2. Drop in the Ansible content. It is collected recursively and each file is
   parsed into one entry of the OPA input document, so a role tree may span as
   many files as it needs.
3. Add an `expected.yaml` listing the rule slugs the case must trip, sorted:

   ```yaml
   violations:
     - get_url_without_checksum
     - task_missing_name
   ```

   Use `violations: []` for a case that must stay clean.
4. Run `python scripts/validate_ansible_examples.py` and iterate until it passes.
