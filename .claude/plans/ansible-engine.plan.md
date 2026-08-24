# Plan: Ansible Analysis Engine

**Source**: "Would it be possible to add an Ansible module to the project?"
**Complexity**: Medium — no new architectural seam, but the widest per-engine surface (backend + rules + frontend + docs + billing)
**Verdict**: Yes. The engine seam already exists and was designed to be widened; Ansible is the cheapest of the plausible next engines because its content is YAML.

## Which "Ansible module"?

The word is overloaded here, and the three readings are different projects:

1. **An Ansible analysis engine in the product** — GreenSecOps scans a repo's playbooks
   and roles the way it scans workflows, Dockerfiles and Terraform, and delivers LLM fixes
   as PRs. **This plan covers this reading**, because it is the one the codebase is shaped
   for: `services/engines.py` exists precisely to make a fourth file-based engine an
   `EngineSpec` rather than a fork.
2. **A custom Ansible module (`library/*.py`) inside `deploy/ansible/`** — a local plugin
   for our own deployment playbooks. Possible and small, but nothing in `deploy/ansible/`
   currently wants one: the roles are `apt`/`docker`/`template`/`copy` tasks that upstream
   modules already cover idempotently. Adding a custom module would mean owning a Python
   plugin, its `ansible-lint` exemptions and its unit tests to replace tasks that are not
   currently broken. Not recommended until a concrete task resists the stock modules.
3. **A published `greensecops.*` Ansible collection** — so *users* could call the
   GreenSecOps API from their own playbooks, the way `action/` lets them call it from a
   workflow. Coherent as a product idea, but it is a distribution project (Galaxy
   namespace, its own release train, its own CI) rather than a change to this repo, and it
   only pays off once there is an API surface worth driving from a playbook. Defer.

A fourth reading — an Ansible **callback plugin** that ships runtime telemetry the way
`action/` does for GitHub Actions — is a genuine follow-on to reading 1, not a substitute
for it. It needs the static engine first (there is nothing to enrich until Ansible findings
exist), and it mirrors `ci_telemetry`/`container_runtime` rather than `iac_terraform`.

## Why this is cheap: the seam is already there

The shared scan → persist → generate → deliver pipeline is engine-agnostic and reads its
nouns from a dataclass. Terraform and Docker are two instances of it; Ansible would be a
third.

| Concern | Where it lives | What Ansible costs |
|---|---|---|
| Fix delivery flow | `backend/app/services/file_fix_delivery.py` | zero — parameterised by `EngineSpec` |
| Fix generation flow | `backend/app/services/file_fix_generation.py:57` | zero — takes a `build_prompt` callable |
| Route bodies | `backend/app/api/engine_routes.py` | zero — shared, keyed on `EngineSpec` |
| Engine nouns | `backend/app/services/engines.py:46` | one `ANSIBLE_ENGINE = EngineSpec(...)` block, ~11 lines |
| Rule catalog | `backend/app/core/rule_registry.py:32` | one line in `_RULES_DIR_TO_DOMAIN` |
| OPA package discovery | `backend/app/services/opa/evaluator.py:150-154` | one `_discover_policy_packages("iac_ansible")` line |
| Rule registration | — | none. Rules are discovered from `app/rules/<domain>/<category>/<slug>.rego`; adding a rule is adding two files |
| Table columns | `backend/app/models/db/mixins.py` | zero — `ScanTargetMixin`, `RepoScanMixin`, `FindingMixin`, `FileFixMixin` already carry them |
| YAML → OPA input with line spans | `backend/app/services/yaml_positions.py` | zero — Ansible is YAML, so no HCL-parser equivalent is needed |

That last row is the reason Ansible is cheaper than the next IaC engine after it.
Terraform needed `services/terraform/hcl_parser.py` (147 lines) to turn HCL into an OPA
input document; Ansible reuses the round-trip converter that Compose and the CI-workflow
engine already share, including its `__start_line__`/`__end_line__` stamping. Verified:
`ruamel` round-trip mode parses `!vault`-tagged values into a `TaggedScalar`, and
`convert_with_positions`' non-JSON-scalar branch (`yaml_positions.py:77`) stringifies it,
so vaulted vars degrade to an opaque string instead of failing a scan.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Engine nouns | `backend/app/services/engines.py:74-98` | `EngineSpec` for target/finding/fix models, branch prefix, labels |
| Tables | `backend/app/models/db/terraform.py` | `Root`/`Scan`/`Finding`/`Fix` quartet over the four mixins, `UniqueConstraint(target, fingerprint)` |
| Migration | `backend/app/alembic/versions/0045_docker_engine.py`, `0046_docker_fix.py` | numbered revision, docstring explaining *why*, tables + indexes |
| Analysis worker | `backend/app/workers/tasks/terraform_analysis.py` | quota gate before fetch, `scan_lock`, `compute_fingerprint`, `resolve_stale_findings`, `compute_score`/`score_to_grade` |
| Fetching | `backend/app/services/github/app_client.py:528` (`fetch_docker_files`) | recursive walk bounded by `_MAX_DEPTH`/`_MAX_FILES`, classification shared with the scanner so fetcher and scanner cannot disagree |
| OPA evaluation | `backend/app/services/opa/evaluator.py:297-330` | per-domain package list + `_evaluate` into a typed violation model |
| Rego rule | `backend/app/rules/container_docker/**` | `# METADATA` block with `custom.severity`/`detection`/`examples`, `violations contains violation if {...}`, `__start_line__` lookup |
| Push dispatch | `backend/app/services/github/event_handlers.py:105` (`enqueue_terraform_scans`) | default-branch-only, `changed_paths` prefix filter, skip `greensecops/` branches |
| Fix prompt | `backend/app/services/llm/terraform_fix_prompt.py` | system+user prompt pair built from file content and its findings |
| Routes | `backend/app/api/routes/terraform.py` | one function per endpoint (operation ids become client method names), bodies delegated to `engine_routes` |
| Mappers | `backend/app/api/mappers/terraform.py` | ORM row → response schema |
| Dashboard | `backend/app/api/routes/overview.py:169`, `frontend/src/lib/engine-meta.ts:15` | overview block + `ENGINE_META`/`SECTION_META` entry |
| Badges | `backend/app/api/routes/badges.py:150-200` | `.svg` + `.json` public endpoints per target |
| Docs | `docs/ext/rego_autodoc.py:43-62` | `_DOMAIN_LABELS` + snippet-language map entry |

## Files to Change

| File | Action | Why |
|---|---|---|
| `backend/app/rules/iac_ansible/{energy,reliability,security,performance,maintainability}/*.rego` | CREATE | The engine's reason to exist. Rules + `_test.rego` pairs; catalogued automatically from their paths |
| `backend/app/models/enums.py` | UPDATE | `RuleDomain.iac_ansible` (:270), `UsageEngine.ansible` (:374), `OverviewEngineKey.ansible` (:411) |
| `backend/app/models/db/ansible.py` | CREATE | `AnsibleProject` / `AnsibleScan` / `AnsibleFinding` / `AnsibleFix` over the existing mixins |
| `backend/app/models/db/__init__.py`, `backend/app/models/__init__.py` | UPDATE | Export the four new models |
| `backend/app/models/db/repository.py`, `pull_request.py` | UPDATE | `ansible_projects` / `ansible_fixes` relationships |
| `backend/app/alembic/versions/0052_ansible_engine.py` | CREATE | Four tables, FKs, the two unique constraints, `rule.domain` enum value |
| `backend/app/core/rule_registry.py` | UPDATE | `"iac_ansible": RuleDomain.iac_ansible` in `_RULES_DIR_TO_DOMAIN` |
| `backend/app/services/opa/evaluator.py` | UPDATE | `IAC_ANSIBLE_POLICY_PACKAGES` + `evaluate_ansible()` |
| `backend/app/services/ansible/discovery.py` | CREATE | Classify a repo path as playbook / role task file / vars file / inventory; the single source both the fetcher and the scanner use |
| `backend/app/services/ansible/parser.py` | CREATE | Multi-document YAML → OPA input, position stamping via `yaml_positions`, FQCN normalisation (see Risks) |
| `backend/app/services/github/app_client.py` | UPDATE | `fetch_ansible_files`, mirroring `fetch_docker_files` |
| `backend/app/services/engines.py` | UPDATE | `ANSIBLE_ENGINE` spec |
| `backend/app/services/delivery_pr.py` | UPDATE | `ansible_fix_branch` prefix |
| `backend/app/services/llm/ansible_fix_prompt.py` | CREATE | Prompt that must preserve Jinja expressions verbatim |
| `backend/app/workers/tasks/ansible_analysis.py` | CREATE | The scan worker (~300 lines, closely mirrors `terraform_analysis.py`) |
| `backend/app/workers/tasks/ansible_fix_generation.py`, `ansible_fix_delivery.py` | CREATE | Thin wrappers over the shared flows (~60 and ~30 lines) |
| `backend/app/workers/celery_app.py` | UPDATE | Register the three tasks |
| `backend/app/services/github/event_handlers.py` | UPDATE | `enqueue_ansible_scans` |
| `backend/app/api/routes/webhooks.py` | UPDATE | Call it from the push handler (:203-211) |
| `backend/app/api/routes/ansible.py`, `backend/app/api/mappers/ansible.py` | CREATE | CRUD + scan/fix endpoints, ORM→schema mapping |
| `backend/app/api/main.py`, `router.py` | UPDATE | Mount the router |
| `backend/app/api/routes/overview.py` | UPDATE | Ansible block in the dashboard overview |
| `backend/app/api/routes/badges.py`, `backend/app/services/badge_signing.py` | UPDATE | Per-project badge endpoints |
| `backend/app/core/plans.py`, `backend/app/services/billing/*` | UPDATE | Meter Ansible scans/fixes against the shared allowance |
| `backend/tests/**` | CREATE | Route, worker, integration and badge tests mirroring the `test_terraform_*` set; repo-wide coverage gate is 90% |
| `frontend/src/client/*` | REGEN | `greensecops-generate-client.md` |
| `frontend/src/routes/_layout/ansible/**`, `AnsibleFindingRow.tsx` | CREATE | List/detail/PR tabs, mirroring the Terraform routes |
| `frontend/src/lib/engine-meta.ts`, `Sidebar/AppSidebar.tsx`, `BadgeGrid.tsx`, `FileViewer.tsx` | UPDATE | Nav entry, dashboard block, badge grid, YAML highlighting |
| `frontend/tests/**` | CREATE | Playwright coverage for the new pages |
| `docs/ext/rego_autodoc.py` | UPDATE | `_DOMAIN_LABELS["iac_ansible"] = "Ansible (IaC)"`, snippet language `yaml` |
| `docs/rule-authoring.rst`, `README.md` | UPDATE | Document the new domain |

## Tasks

### Task 1: Rule corpus first, engine second
- **Action**: Write 10–15 `iac_ansible` rules with their `_test.rego` pairs before any
  plumbing — e.g. `become` without a named user, `shell`/`command` where a module exists,
  `latest` package state (non-reproducible), missing `changed_when` on `command`,
  `validate_certs: false`, world-readable `mode`, plaintext secrets in vars, missing
  `no_log` on secret-bearing tasks, unpinned `galaxy` requirements, `ignore_errors: true`.
  Run them against fixtures with `opa test`.
- **Why first**: the rules are the only part that cannot be copied from an existing engine,
  and they decide whether the engine is worth its plumbing. If 15 defensible rules are hard
  to write, stop here having spent a day, not a fortnight.
- **Validate**: `opa test backend/app/rules/iac_ansible` green; `discover_rules()` catalogues
  them once the enum lands.

### Task 2: Discovery + parser
- **Action**: `services/ansible/discovery.py` classifies paths (`playbooks/*.yml`,
  `roles/*/tasks/*.yml`, `roles/*/handlers/*.yml`, `group_vars/`, `host_vars/`,
  `site.yml`); `services/ansible/parser.py` loads multi-document YAML round-trip, stamps
  spans and normalises module keys (see Risks).
- **Mirror**: `services/docker/compose_parser.py` + `yaml_positions.py`
- **Validate**: unit tests over fixtures, including this repo's own `deploy/ansible/` tree.

### Task 3: Models + migration
- **Mirror**: `models/db/terraform.py`, `alembic/versions/0045_docker_engine.py`
- **Validate**: `greensecops-db-migration.md` — autogenerate, review, upgrade, downgrade.

### Task 4: Scan worker + OPA wiring
- **Mirror**: `workers/tasks/terraform_analysis.py`, `evaluator.py:297`
- **Validate**: integration test scanning a fixture project end to end.

### Task 5: Fix generation + delivery
- **Action**: `ANSIBLE_ENGINE` spec, prompt module, two thin task wrappers.
- **Mirror**: `services/engines.py:74`, `terraform_fix_generation.py`
- **Validate**: fix-generation and fix-delivery tests with a stubbed provider.

### Task 6: API + client + frontend
- **Validate**: `greensecops-generate-client.md`, then Playwright.

### Task 7: Billing, badges, docs, dashboard
- **Validate**: billing tests assert every engine is metered; docs build.

## Risks and Unknowns

**Ansible's schema is conventions, not a schema.** Terraform has typed blocks and Compose
has a spec; an Ansible task is a mapping whose *module name is a key* alongside `name`,
`when`, `loop`, `become` and the rest. Rules must therefore identify the module key by
elimination against the known task-keyword set, and that set changes between Ansible
versions. Pin the keyword list in one Rego lib file (`rules/lib/ansible.rego`, mirroring
`rules/lib/workflow.rego`) so a version bump is one edit.

**FQCN aliasing.** `apt`, `ansible.builtin.apt` and a `collections:`-scoped short name are
the same module. Normalise to the FQCN in the parser, not in each rule, or every rule
carries the alias table.

**Jinja2 is opaque to static analysis.** `mode: "{{ file_mode }}"` cannot be judged without
resolving vars across `group_vars`, `host_vars`, role defaults and `set_fact`. Do not
attempt resolution. Rules should skip templated values rather than guess, and the finding
message should say so — a false positive on a templated value is worse than a miss.

**LLM fixes on templated YAML are riskier than on HCL.** A rewrite that reformats a Jinja
expression or drops a `!vault` tag breaks a deployment silently. Mitigations: constrain the
prompt to minimal edits, and add a post-generation guard that re-parses the patched file
and rejects the fix if the set of Jinja expressions or tagged scalars changed. This guard
does not exist for the other engines and is genuinely new work.

**`include_tasks`/`import_role` indirection.** A file-scoped scan sees each task file
alone. Accept that: the finding is anchored to the file that contains the offending task,
which is also the file a fix rewrites. Cross-file analysis is a later phase, if ever.

**What counts as a target.** Terraform registers roots by hand; Docker auto-creates a
default target. Ansible sits between: a repo may have one `site.yml` or a dozen roles. The
plan assumes an `AnsibleProject` = a directory registered like a Terraform root, defaulting
to the repo root. Worth confirming before Task 3, since it is the one decision the schema
cannot walk back cheaply.

**Rule-domain proliferation on the dashboard.** `OverviewEngineKey` currently drives three
collapsible sections. A fifth engine makes the dashboard the constraint, not the backend —
`SECTION_META` will want an "Infrastructure" section holding Terraform, Ansible and cloud
posture rather than a fourth top-level section.

## Effort

The Docker engine is the closest measured precedent: roughly 8,600 lines across backend
code, rules and tests, not counting the frontend. Ansible should come in under that — no
new parser toolchain, and the delivery/generation/route flows were extracted into shared
modules *after* Docker was built, so this engine pays none of the duplication Docker did.
Realistic shape: Task 1 in a day, Tasks 2–5 the bulk of the work, Tasks 6–7 mostly
mechanical.

## Recommended sequencing

Ship Task 1 alone first, as a rules-only PR that lands the `RuleDomain` value, the registry
entry and the OPA package list. It is independently reviewable, produces the docs pages,
and proves the rule corpus before committing to four tables and a migration.
