# Ansible Analysis Engine

## Context

GreenSecOps grades software-delivery pipelines across five axes (energy, reliability,
security, performance, maintainability) using Rego rules evaluated by OPA, then delivers
LLM-generated fixes as GitHub PRs. It ships six engines today: CI workflow, CI telemetry,
Terraform, AWS cloud posture, Docker/Compose static, and Docker runtime.

Ansible is the obvious next input domain and the cheapest one to add, because its content is
YAML: `services/yaml_positions.py` already converts a ruamel round-trip tree into a
JSON-safe document with `__start_line__`/`__end_line__` spans, so no new parser toolchain is
needed (Terraform needed `hcl_parser.py`; Docker needed `dockerfile_parser.py`). The
scan → persist → generate → deliver pipeline is already parameterised behind
`services/engines.py::EngineSpec`, so a fourth file-based engine is a spec plus its nouns
rather than a fork.

Outcome: a repository's playbooks and roles are scanned on every default-branch push,
findings are graded and shown in the dashboard, and fixes arrive as a PR — the same loop the
other engines already run.

**Verified empirically before planning** (against this repo's own `deploy/ansible/`):
`convert_with_positions` produces correct per-play and per-task line numbers for top-level
YAML sequences; `load_all` handles multi-document files; `!vault` parses to a `TaggedScalar`
that the converter stringifies rather than crashing on; and a shape-based classifier
correctly identified `playbooks/*.yml` and `roles/*/tasks/main.yml` as Ansible while
rejecting `compose.yml`, `.github/workflows/opa.yml`, `.pre-commit-config.yaml`,
`inventory/aws_ec2.yml` and `group_vars/all.yml`.

## Decisions taken

| Decision | Choice |
|---|---|
| Delivery | Three phased PRs: rules → engine → fixes |
| Target registration | Manual, Terraform-style: an `AnsibleProject` with an explicit `root_path`. No auto-creation at installation sync. |
| Scope | Dashboard UI, dogfood CI gate on `deploy/ansible/`, LLM fix generation + delivery, `landing/ansible.html` |
| Dashboard placement | Fold into the existing **Infrastructure** section, not a new top-level section (see *UI placement* below) |

## Naming contract

Fix these once; every file below depends on them.

| Thing | Value |
|---|---|
| Rules directory | `backend/app/rules/iac_ansible/` |
| `RuleDomain` member | `iac_ansible = "iac_ansible"` |
| `UsageEngine` member | `ansible = "ansible"` — **must equal `EngineSpec.name`** (`api/engine_routes.py:113` does `UsageEngine(spec.name)`) |
| `EngineSpec.name` / `label` | `"ansible"` / `"Ansible"` |
| Tables | `ansible_project`, `ansible_scan`, `ansible_finding`, `ansible_fix` |
| Models | `AnsibleProject`, `AnsibleScan`, `AnsibleFinding`, `AnsibleFix` |
| FK column | `ansible_project_id` |
| API prefix | `/api/v1/ansible-projects` |
| **Path parameter** | **`project_id`** — *not* `target_id` or `root_id` |
| Fix branch | `greensecops/ansible-<id[:8]>` via `ansible_fix_branch` |
| `OverviewEngineKey` | `ansible = "ansible"`, section `infra` |

`api/router.py::ORG_RESOLVERS` (:179-189) is keyed by **path-parameter name** — `target_id`
resolves to `DockerTarget`, `root_id` to `TerraformRoot`. Reusing either name silently
routes Ansible role checks to the wrong model. Add `"project_id": OrgResolver(_org_of_ansible_project, "Ansible project not found")`.

`EngineSpec.target_not_found` derives from `__tablename__`, so `ansible_project_not_found`
comes for free.

## Architecture

### The OPA input document

Terraform and Docker each merge every fetched file into one document. Ansible files are not
mergeable — a task file is not a playbook — so the document is an **envelope of files**,
still one OPA request per package:

```json
{"files": [
  {"__ansible_file": "playbooks/deploy.yml", "kind": "playbook",
   "plays": [{"name": "...", "hosts": "...", "tasks": [...], "__start_line__": 18, "__end_line__": 32}]},
  {"__ansible_file": "roles/common/tasks/main.yml", "kind": "tasks", "tasks": [...]},
  {"__ansible_file": "group_vars/all.yml", "kind": "vars", "vars": {...}},
  {"__ansible_file": "requirements.yml", "kind": "requirements", "requirements": {...}}
]}
```

The envelope is not just tidiness — it is what makes the engine safe under CI.
`scripts/validate_examples.py` evaluates `examples/deploy.yml` (a **GitHub Actions
workflow**) against `data.aggregate.all_violations`, i.e. against every domain's packages.
Because every Ansible rule begins `some f in input.files`, and a workflow document has no
`files` key, the whole suite is vacuously silent on foreign documents. A bare per-file
document (a top-level task list) would have no such guard, and a rule keyed on a missing
field would fire on the reference workflow and break the build — the trap documented at
`docs/rule-authoring.rst:67-71`.

**Rules must key on presence-and-wrongness, never on absence of a list.**

### Parser: flatten blocks in Python, not in Rego

Rego forbids recursive rule definitions, so `block`/`rescue`/`always` nesting cannot be
walked by a recursive helper. `services/ansible/parser.py` therefore emits a **flat** task
list per file/play, each task carrying its own `__start_line__`/`__end_line__` plus
`__block_depth__`. Rules see one uniform sequence; the nesting logic is Python, unit-tested
in pytest, and never a Rego puzzle.

`services/ansible/discovery.py` classifies by **shape, not path** — verified above to reject
Compose files, GitHub workflows and inventories. Path is used only for the two kinds shape
cannot distinguish (`requirements.yml`, `group_vars/`/`host_vars/`). Classification lives in
one module imported by both the fetcher and the scanner, mirroring the comment at
`app_client.py:537-541`: a mismatch would silently drop files from a scan.

### `rules/lib/ansible.rego`

`backend/app/rules/lib/` is excluded from rule discovery (`core/rego_metadata.py::LIB_DIR`)
but **is** shipped to the OPA server (`opa/Dockerfile:10` copies all of
`backend/app/rules`), so a helper file costs nothing. Model on `lib/workflow.rego`.

```rego
package greensecops.lib.ansible

task_keywords := {"name", "when", "become", "become_user", "loop", "with_items", ...}
module_key(task) := k          # the one key not a task keyword; undefined if ambiguous
module_name(task) := fqcn      # short name → ansible.builtin.X via an alias map
short_name(task) := last       # trailing dot segment
is_templated(value)            # value contains {{ }} or {% %}
tasks_of(file)                 # every flattened task: playbook plays and task files alike
plays_of(file)
arg(task, key)                 # module argument lookup
line(task) := object.get(task, "__start_line__", null)
```

Ansible rules may also `import data.greensecops.lib.workflow as wf` and reuse its
engine-agnostic credential helpers — `wf.looks_high_entropy`, `wf.is_placeholder`,
`wf.known_credential` — which is what keeps `hardcoded_secret_in_vars` honest.

`opa fmt` indents with **tabs**. Write rules tab-indented or the `backend/`
pre-commit hook rewrites them.

### Scoring: per-file groups

`compute_score(pooled, groups)` (`services/scoring.py:50`) averages per-group scores then
subtracts pooled penalties. Terraform pools (one logical module); Docker groups per file
after measuring that pooling scored this repo 0.0/F against 69.6/C
(`docker_analysis.py:218-233`). An Ansible project is N independent files, so **follow
Docker**: `score_groups = {f.path: violations_for(f.path) for f in fetched}`.

### UI placement

Reuse `OverviewSection.infra` rather than adding a section. A new `OverviewSection` value
would need `SECTION_ICON` in `dashboard.tsx:61-65` (an exhaustive `Record`, so a compile
error — fine) **and** the hardcoded title/description ternaries at `dashboard.tsx:456-466`,
which are *not* exhaustive and would silently label the new section "Infrastructure"
anyway. Folding in means only `ENGINE_META` and `SECTION_META.infra.engines` change.

`ENGINE_META[engine.engine]` is indexed **without a fallback** by three dashboard components
(`CategoryEngineHeatmap.tsx:99`, `EngineOverviewTable.tsx:39`, `EngineDetail.tsx:20`). The
backend enum and the `ENGINE_META` entry must ship in the same PR or the dashboard crashes
on `undefined.label`.

---

## PR 1 — Rule corpus and domain wiring

Independently reviewable, produces the docs pages, and proves the rules before any schema is
committed. No tables, no migration.

### The corpus

Fifteen rules. The right-hand column is the finding that shaped the list: **each rule was
checked against this repo's own `deploy/ansible/` tree**, because PR 1 also lands the
zero-violation dogfood gate.

| Category | Slug | Severity | Fires on `deploy/ansible/`? |
|---|---|---|---|
| energy | `package_state_latest` | medium | no (all `state: present`) |
| energy | `apt_cache_always_updated` | low | no |
| energy | `package_module_in_loop` | medium | no |
| energy | `git_module_without_version` | medium | no (`git` unused) |
| energy | `unarchive_remote_src_without_creates` | low | no (`unarchive` unused) |
| reliability | `command_without_changed_when` | medium | no — every `command`/`shell` sets it |
| reliability | `ignore_errors_true` | medium | no |
| reliability | `get_url_without_checksum` | high | **YES** — `roles/docker/tasks/main.yml` |
| reliability | `service_not_enabled` | medium | no (`enabled: true` throughout) |
| reliability | `galaxy_requirement_unpinned` | medium | no (both collections pinned) |
| security | `validate_certs_disabled` | high | no |
| security | `hardcoded_secret_in_vars` | critical | no — but see the trap below |
| security | `no_log_missing_on_secret_task` | high | no |
| security | `shell_with_unquoted_variable` | high | **YES** — two ECR-login shells |
| maintainability | `task_missing_name` | low | no |

Cut from the draft list, with reasons worth recording:

- **`fact_gathering_not_narrowed`** (energy) — would fire on all five plays in
  `playbooks/deploy.yml`, and `roles/docker/defaults/main.yml` genuinely needs
  `ansible_facts['architecture']`. Whether a play's roles use facts is not decidable from one
  file. Noise on correct code; cut.
- **`serial_one_on_large_play`** (performance) — `serial: 1` is deliberate on load-balanced
  plays here and is documented as such. Not statically decidable; cut.
- **`command_where_module_exists`** (performance) — kept out of v1 rather than cut: it is
  only safe if scoped to a fixed list of commands with a genuine builtin equivalent
  (`yum`, `apt`, `systemctl`, `useradd`, `mkdir`, `chmod`, `curl`, `wget`). `aws ssm` and
  `docker buildx` have no module, so a naive version fires all over this repo. Add it in a
  follow-up with the allow-list approach.
- **Performance ends up with no rules in v1.** That is honest — Ansible's performance
  characteristics are mostly connection- and strategy-level (`forks`, `pipelining`,
  `strategy`), which live in `ansible.cfg`, an INI file this engine does not read.

**Trap to respect in `hardcoded_secret_in_vars`:** `group_vars/all.yml` defines
`greensecops_base_required_secrets` — a **list of secret names** (`FIRST_SUPERUSER_PASSWORD`,
`GITHUB_CLIENT_SECRET`, …). A rule that keys on "variable name matches
`secret|password|key`" fires on it. Key instead on a *mapping key* matching the pattern
whose *value* is a non-templated literal passing `wf.looks_high_entropy` and failing
`wf.is_placeholder`.

### The dogfood gate needs two real fixes to `deploy/ansible/`

`scripts/validate_deploy_terraform.py` fails on **any** violation, on the principle that the
reference deployment of a product that scans Terraform must pass its own rules. Matching that
bar for Ansible means PR 1 also fixes the two genuine findings its own rules produce:

1. `roles/docker/tasks/main.yml` — the Compose plugin is downloaded with no `checksum:`.
   `docker_compose_arch` is templated (`aarch64` or `x86_64`), so add a
   `docker_compose_sha256` map in `roles/docker/defaults/main.yml` keyed by arch and
   `checksum: "sha256:{{ docker_compose_sha256[docker_compose_arch] }}"`.
2. `roles/docker/tasks/main.yml` and `playbooks/build.yml` — the ECR-login `shell` cmd
   interpolates `{{ greensecops_region }}` and `{{ greensecops_config.ECR_REGISTRY }}`
   unquoted. Apply the `| quote` filter, which is exactly the fix the rule recommends.

Both are improvements on their own merits. If either turns out to be contentious in review,
the fallback is to give `validate_deploy_ansible.py` an `expected.yaml` allow-list like the
example validators use — but prefer the fixes.

### Files

| File | Action |
|---|---|
| `backend/app/rules/iac_ansible/<category>/<slug>.rego` + `_test.rego` | CREATE (15 pairs) |
| `backend/app/rules/lib/ansible.rego` + `_test.rego` | CREATE |
| `backend/app/models/enums.py` | `RuleDomain.iac_ansible`. **No migration** — `rule.domain` is a plain `AutoString`, added by `0042`; `0045_docker_engine.py:8` says so explicitly. |
| `backend/app/core/rule_registry.py:32` | `"iac_ansible": RuleDomain.iac_ansible` |
| `backend/app/services/opa/evaluator.py:150-154` | `IAC_ANSIBLE_POLICY_PACKAGES = _discover_policy_packages("iac_ansible")` |
| `examples/ansible/<case>/` + `expected.yaml` | CREATE — at least one deliberately bad project, one hardened project tripping nothing, and one role-layout case. Follow `examples/docker/README.md`; adding a case is a no-code operation. |
| `examples/ansible/README.md` | CREATE |
| `scripts/opa_ansible_eval.py` | CREATE — reuses `opa_eval.domain_query`/`run_opa_eval` |
| `scripts/validate_ansible_examples.py` | CREATE — mirror of `validate_docker_examples.py` |
| `scripts/validate_deploy_ansible.py` | CREATE — mirror of `validate_deploy_terraform.py`, zero-violation bar |
| `deploy/ansible/roles/docker/{tasks,defaults}/main.yml`, `playbooks/build.yml` | UPDATE — the two fixes above |
| `.github/workflows/opa.yml` | UPDATE — **both** the `push` and `pull_request` path lists (they are duplicated), plus two new steps |
| `.pre-commit-config.yaml` | ADD a `deploy-ansible-opa` hook mirroring `deploy-terraform-opa` (:183-188) |
| `docs/ext/rego_autodoc.py` | `_DOMAIN_LABELS["iac_ansible"] = "Ansible (IaC)"`; `_EXAMPLE_LANGUAGES["iac_ansible"] = "yaml"`; fix the stale "Four analysis engines" prose at :286 |
| `docs/index.rst`, `docs/rule-authoring.rst` | UPDATE — engine count (currently "six"), the bullet list, the engine→input table, and the "six existing engines are the template" line |

### Validation

```bash
opa check backend/app/rules
opa test  backend/app/rules -v
python scripts/validate_ansible_examples.py
python scripts/validate_deploy_ansible.py          # must report zero
python scripts/validate_examples.py                # proves no Ansible rule fires on a GH workflow
cd backend && uv run pytest tests/core/ -v         # rule_registry catalogues the new domain
```

`_EXAMPLE_LANGUAGES` is not cosmetic: the docs image builds with `sphinx-build -W`
(`docs/Dockerfile:34`), and an unlisted domain falls back to `text`, whose Pygments lex
failure becomes a build error. Every rule also needs `custom.examples.{bad,good,fix}` —
`rego_autodoc._warn_rule` warns on a missing one, and `-W` turns that into a failure.

---

## PR 2 — Tables, scan worker, API, dashboard

### Backend

| File | Action |
|---|---|
| `backend/app/services/ansible/discovery.py` | CREATE — `classify_ansible_file(path, content) -> str \| None` returning `playbook`/`tasks`/`vars`/`requirements` |
| `backend/app/services/ansible/parser.py` | CREATE — per-file parse, block flattening, span stamping via `yaml_positions`, FQCN normalisation; `merge_ansible_files(files) -> dict` builds the envelope |
| `backend/app/models/db/ansible.py` | CREATE — the quartet over `ScanTargetMixin` / `RepoScanMixin` / `FindingMixin` / `FileFixMixin`. `root_path: str = Field(max_length=512)` with **no default** (manual registration). Unique constraints `uq_ansible_project_repo_path`, `uq_ansible_finding_project_fingerprint`, `uq_ansible_fix_project_file`. `rule_id` FK RESTRICT, `fix_id` FK SET NULL. |
| `backend/app/models/db/{__init__,repository,pull_request}.py`, `models/__init__.py` | UPDATE — exports and `ansible_projects` / `ansible_fixes` back-populates |
| `backend/app/models/schemas.py` | CREATE the five publics off the shared bases (`ScanTargetPublicBase`, `RepoScanPublicBase`, `FixablePublicBase`, `FilePublicBase`, `FileFixPublicBase`) |
| `backend/app/alembic/versions/0052_ansible_engine.py` | CREATE — chain from head `0051`. Four tables; enum columns are plain `AutoString` with string server defaults, per the house style. Add `ix_ansible_finding_fingerprint`, `ix_ansible_finding_status`, and `ix_ansible_scan_project_created` on `(ansible_project_id, created_at DESC)` via raw SQL as `0051` does. |
| `backend/app/services/opa/evaluator.py` | `AnsibleOpaViolation` dataclass (`rule_slug, severity, category, message, file_path, line_start, line_end, context, discriminator, play_name, task_name`) + `evaluate_ansible(document)`, default category `"reliability"` |
| `backend/app/services/github/app_client.py` | `AnsibleFileContent` dataclass + `fetch_ansible_files`, classification via `classify_ansible_file`, caps mirroring `_DOCKER_MAX_{FILES,DEPTH}`, skip-dirs including `.github` |
| `backend/app/workers/tasks/ansible_analysis.py` | CREATE — mirror `terraform_analysis.py`. **Must expose `_run_ansible_scan_impl`, `_fetch_ansible_files` and `_evaluate` as module-level names** — that trio is the seam every worker test patches. Fingerprint on `(project.id, rule.id, v.file_path, v.discriminator)`. Per-file score groups. |
| `backend/app/workers/celery_app.py` | `include` entry + `task_routes` `"ansible_analysis.*": {"queue": "analysis"}` |
| `backend/app/workers/tasks/maintenance.py:106` | add `AnsibleScan` to the sweeper tuple |
| `backend/app/workers/tasks/polling.py:147-168` | add the third `enqueue_ansible_scans` call |
| `backend/app/services/github/event_handlers.py` | `enqueue_ansible_scans` mirroring `enqueue_terraform_scans` (default-branch-only, `changed_paths` prefix filter, skip `greensecops/` branches) |
| `backend/app/api/routes/webhooks.py:203-218` | call it from the push handler |
| `backend/app/api/routes/ansible.py`, `api/mappers/ansible.py` | CREATE — the 11 core endpoints Terraform has, path param `project_id` |
| `backend/app/api/{main,router}.py` | mount the router; add `_org_of_ansible_project` + the `"project_id"` `ORG_RESOLVERS` entry |
| `backend/app/api/routes/overview.py` | add the `_OverviewEngine` descriptor (`key=ansible`, `section=infra`) |
| `backend/app/api/routes/badges.py` | `_ansible_project_badge_grade` + `.svg`/`.json` endpoints. `badge_signing.py` needs no change — it signs `str(id)`. |
| `backend/app/core/plans.py` | prose only ("five engines" → six; the Pro feature string). **If the `features` tuple changes, re-run `python scripts/render_landing_pricing.py`** — `opa.yml` re-checks it with `--check`. |

Quota and metering are two call sites, following Terraform exactly:
`quota.exhausted_message(..., engine=UsageEngine.ansible)` before the fetch in the worker, and
`usage.record_for_repo(..., engine=UsageEngine.ansible, source_type="ansible_scan", ...)`
after the scan row exists. Nothing changes in `PlanLimits`, `PLANS`, `quota._LEDGER_METERS`,
`lifecycle.py`, `owner.py` or `notifications.py` — `UsageEngine` is a ledger tag, not a limit
key. Add the enum member **before** any row is written: `usage.period_breakdown` coerces
stored strings back through `UsageEngine(...)` and raises `ValueError` on an unknown value.

### Frontend

Regenerate the client first: `bash scripts/generate-client.sh` — it rewrites **both**
`frontend/src/client/` and `action/src/client/`; stage both.

| File | Action |
|---|---|
| `frontend/src/lib/engine-meta.ts` | `ENGINE_META.ansible` (icon, label, blurb, `to: "/infrastructure"`); add `"ansible"` to `SECTION_META.infra.engines` |
| `frontend/src/lib/delivery.ts` + `delivery.test.ts` | `ansibleFixBranch`, mirroring the backend prefix |
| `frontend/src/routes/_layout/infrastructure/$repoId.tsx` | add an "Ansible" tab to `navItems` |
| `frontend/src/routes/_layout/infrastructure/$repoId/ansible.tsx` | CREATE — mirror `terraform.tsx`, `FileViewer grammar="yaml"` (already supported; no new Prism grammar) |
| `frontend/src/routes/_layout/infrastructure/index.tsx` | add an Ansible-projects group with a register form |
| `frontend/src/components/AnsibleFindingRow.tsx` | CREATE (~22 lines, mirrors `TerraformFindingRow`) |
| `frontend/src/routes/_layout/badges/ansible.tsx` | CREATE via `BadgePage`; add the tab to `badges.tsx:19-23` |
| `frontend/src/components/Sidebar/AppSidebar.tsx` | add `{ title: "Ansible", segment: "ansible" }` to `infraSubItems` |
| `frontend/src/routeTree.gen.ts` | regenerate by running `bun run dev` once, then commit — **there is no pre-commit or CI drift check for this file** |

`EnginePullRequestsTab`, `FindingRow`, `FileViewer`, `BadgeGrid` need no code change — only
their docstrings, which name the engines.

### Tests

Mirror the Terraform set: `tests/api/routes/test_ansible.py`, `test_ansible_badges.py`,
`tests/workers/tasks/test_ansible_analysis.py`, `test_ansible_analysis_integration.py`,
`tests/services/test_ansible_parser.py`, `test_ansible_discovery.py`.

Fixtures: create `backend/tests/fixtures/ansible/<case>/` with vendored real-world roles plus
a recorded `expected.json`, and `scripts/regenerate_ansible_fixtures.py` with a `--check`
mode wired into `opa.yml`. This matters because **the pytest environment has no `opa`
binary** — integration tests replay recorded violations while everything else (parse, merge,
fingerprint, persist, score) runs for real. A rule change would otherwise invalidate the
recording silently.

Add the same whitespace-hook exclusions the Terraform corpus has
(`trailing-whitespace`, `end-of-file-fixer`, `mixed-line-ending` all carry
`exclude: ^backend/tests/fixtures/terraform/.*\.tf$`) so vendored YAML stays byte-for-byte.
Keep the corpus under `backend/tests/fixtures/ansible/` and **not** anywhere under
`deploy/` — the `ansible-lint` hook and the `deploy-checks.yml` ansible job lint everything
in `deploy/ansible/` and would fail on deliberately bad fixtures.

E2E: `frontend/tests/ansible.spec.ts` modelled on `docker.spec.ts`; extend
`frontend/tests/utils/mocks.ts` with the Ansible mocks and the overview block. ⚠️
`dashboard.spec.ts:62` and `:128` iterate **hardcoded** engine and section arrays — both must
grow, and the expected-count comment at `:50` needs updating.

Coverage: the global gate is 90% (`test-backend.yml:69`) and `app/services/ansible/**` and
the worker modules are **not** in the coverage `omit` list. They need real tests or they drag
the whole number down.

---

## PR 3 — LLM fix generation and delivery

| File | Action |
|---|---|
| `backend/app/services/delivery_pr.py` | `ANSIBLE_FIX_BRANCH_RE` + `ansible_fix_branch` |
| `backend/app/services/engines.py` | `ANSIBLE_ENGINE = EngineSpec(...)`, `files_description="Ansible playbooks and roles"` |
| `backend/app/services/llm/ansible_fix_prompt.py` | CREATE — constrain to minimal edits; state that Jinja expressions and tagged scalars must be reproduced verbatim |
| `backend/app/services/ansible/fix_guard.py` | CREATE — the differential guard below |
| `backend/app/workers/tasks/ansible_fix_generation.py`, `ansible_fix_delivery.py` | CREATE — thin wrappers (~60 and ~30 lines) |
| `backend/app/workers/celery_app.py` | `include` + `task_routes` entries for the `fixes` queue |
| `backend/app/api/routes/ansible.py` | add `POST /{project_id}/fixes` and `POST /{project_id}/deliver` via `prepare_pending_fix` |
| `frontend/src/routes/_layout/infrastructure/$repoId/pull-requests.tsx` | extend to carry Ansible alongside Terraform, or add a sibling tab |

### The fix guard, and a deliberate change to shared code

A rewrite that reformats a Jinja expression or drops a `!vault` tag breaks a deployment
silently. No other engine has this exposure — HCL and Dockerfiles have no equivalent of a
value that must survive byte-identical.

The guard is differential, so it needs the original content. The shared contract today is
`validate: Callable[[str, str], str | None]` — `(file_path, patched_content)` — called at
`file_fix_generation.py:127`, and the original is fetched *inside* `generate_file_fix`, so a
closure in the task cannot capture it. **Widen the contract to
`(file_path, original_content, patched_content)`** and update the two existing `_validate`
implementations to the new arity (they ignore the extra argument). Three files, small diff,
and it is the honest design — the alternative is memoising the fetch, which is fragile.

What the guard checks:

1. The patched content parses as YAML and classifies to the **same kind** as the original.
2. Every **variable name** referenced inside `{{ }}`/`{% %}` in the original still appears in
   the patched file. Comparing variable *names* rather than raw expression text is
   deliberate: `{{ region }}` → `{{ region | quote }}` is precisely the fix
   `shell_with_unquoted_variable` asks for, and a raw-text comparison would reject it.
3. Every **tag** on a tagged scalar in the original (`!vault`, `!unsafe`) is still present.

What it must **not** reject: added expressions, added or removed tasks, reordering, comment
changes. Containment in one direction only — original ⊆ patched — never equality.

---

## Cross-cutting gotchas

- **Seed side effect.** `initial_data.py:20-32` fires `reanalyze_all_repositories.delay()`
  when `_seed_rules` returns new slugs and at least one repository exists. Shipping 15 new
  rules therefore triggers a full re-analysis fan-out on the first deploy after release.
  Expected, but worth saying out loud before it surprises someone.
- **A malformed rule blocks startup.** `discover_rules` raises on missing or invalid
  METADATA, which propagates out of `init_db` and fails `prestart` — the backend will not
  start. Intended, and loud.
- **An unregistered rule silently drops findings.** Unlike the CI-workflow engine, the
  file-based workers `logger.warning` and `continue` on a slug with no `Rule` row. If a
  `.rego` file ships without its row, its findings vanish with only a log line.
- **`opa fmt`/`opa check` pre-commit hooks need a Docker daemon** at commit time
  (`backend/.pre-commit-config.yaml:28-40`).
- **`generate-openapi-client` fires on any `backend/app/**.py` change** and rewrites the
  frontend *and* action clients. Re-stage both.
- **PR labels.** `.github/workflows/labeler.yml` requires exactly one of
  `breaking, security, feature, bug, refactor, upgrade, docs, lang-all, internal`, and
  auto-labelling only covers `docs`/`upgrade`/`internal`. A product-source PR matches none of
  them — pass `--label feature` explicitly.
- **Commit messages** must be conventional (`feat:`, `docs:`, …) — enforced at `commit-msg`.
- **`test-backend.yml` has `timeout-minutes: 5`** and `playwright.yml` has 15. A large new
  suite pushes toward both.
- **No test asserts that every `UsageEngine` member is metered**, despite the enum docstring
  claiming otherwise. Adding `tests/workers/tasks/test_billing_enforcement.py` coverage for
  the Ansible worker (the existing file covers only Terraform) is the cheap way to keep this
  honest.

## Landing page (final, optional task)

`landing/ansible.html` mirroring `landing/terraform.html`, plus links from `features.html`
and `index.html`. The nav partial does not enumerate engines, so no partial changes. Run
`python landing/build.py` and commit — `opa.yml` re-checks with `--check`.

## Verification

End to end, after PR 2:

```bash
# Backend
docker compose up -d db redis mailcatcher
cd backend && uv run bash scripts/prestart.sh          # migrations + rule seed
uv run pytest tests/ -k ansible -v
uv run coverage run -m pytest tests/ && uv run coverage report --fail-under=90
uv run ruff check app --fix && uv run ruff format app && uv run mypy app --ignore-missing-imports

# Rules
opa check backend/app/rules && opa test backend/app/rules -v
python scripts/validate_ansible_examples.py
python scripts/validate_deploy_ansible.py
python scripts/regenerate_ansible_fixtures.py --check

# Client + frontend
bash scripts/generate-client.sh && git diff --name-only frontend/src/client/ action/src/client/
cd frontend && bun run typecheck && bun run lint && bun run test:unit

# E2E
cd frontend && bunx playwright test tests/ansible.spec.ts tests/dashboard.spec.ts
```

Then drive the real UI with the `verify` skill: register an Ansible project against a repo
containing playbooks, trigger a scan, confirm findings render with correct line anchors in
`FileViewer`, and confirm the dashboard's Infrastructure section shows the Ansible block.
Note the `verify` skill's warning — the backend test suite's conftest teardown deletes all
users, so re-run `uv run python app/initial_data.py` after pytest before logging in.
