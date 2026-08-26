# GreenSecOps

Grades a team's software delivery pipeline across several analysis engines, all
sharing one Rego rule catalog and one grading model.

`development.md` covers running the stack; `deployment.md` covers shipping it.
This file is the conventions a change has to fit into.

## Layout

```
backend/app/          FastAPI + SQLModel + Celery
  api/routes/         one module per resource, mounted in api/main.py
  api/router.py       RoleRouter — every endpoint declares who may call it
  models/db/          tables, one module per domain
  models/schemas/     public API shapes, split on the same lines
  models/enums.py     every enum, including the vocabulary below
  services/           the domain logic; workers and routes are built from it
  workers/tasks/      Celery tasks — thin wrappers over services/
  rules/<domain>/<category>/<slug>.rego
frontend/src/         React + TanStack Router + Query, shadcn/ui
  client/             GENERATED from the backend's OpenAPI — never hand-edit
action/               the GitHub Action that reports telemetry
```

## One vocabulary

Every engine names the same three things the same way. Read one engine and you
have read them all.

| Concept | Tables |
|---|---|
| a run of an engine over a target | `workflow_scan`, `terraform_scan`, `docker_scan`, `cloud_scan` |
| a rule violation it found | `workflow_finding`, `terraform_finding`, `docker_finding`, `cloud_finding` |
| an LLM rewrite of an offending file | `workflow_fix`, `terraform_fix`, `docker_fix` |

Two enums, on two different axes, and they are **not** one-to-one:

- `Engine` — which analysis engine: `workflow`, `terraform`, `docker`, `cloud`,
  `telemetry`. Usage records tag themselves with it and the dashboard keys its
  stat blocks by it.
- `RuleDomain` — which Rego package a rule lives in. **Every member is exactly a
  directory name under `app/rules/`**, which is what lets the seeder derive it
  with `RuleDomain(dir_name)` instead of a lookup table. Keep that true.

`ENGINE_OF_DOMAIN` maps between them. It is many-to-one: `container_docker` and
`container_runtime` rules both grade the Docker engine.

Status enums are shared too — `ScanStatus`, `FindingStatus`, `FixStatus` — as
are `Severity` and `Category`. If you find yourself adding an engine-specific
copy of one, that is the smell this whole vocabulary exists to prevent.

## Layering

`api/` and `workers/` are both built on `services/`. Services must not import
from workers: if a service needs work done later, it dispatches a Celery task at
call time and the deferred import is marked as such.

Adding an engine touches `services/engines.py` — `EngineSpec` (what the shared
scan/fix/deliver flows need) and `OverviewSpec` (what the dashboard aggregation
reads). They are separate structs on purpose: cloud has no files or fixes, so
merging them would leave half the fields `None`. An import-time check asserts
they agree wherever both describe the same engine.

The shared flows themselves live in `services/scan_runner.py`,
`services/file_fix_generation.py` and `services/file_fix_delivery.py`. A worker
should be a Celery task, a lock, a retry policy and a spec — if one is growing
a scan pipeline of its own, it is diverging from the others.

## Authorization

Every endpoint declares its caller in the decorator:

```python
@router.get("/{repo_id}", role=Role.org_member, response_model=RepositoryPublic)
```

`role` is keyword-only with no default, so a forgotten one fails at import
rather than shipping unguarded. `tests/api/test_roles.py` walks `app.routes`
against the registry to catch anyone reaching for a plain `APIRouter`.

## The URL grammar

One shape covers the whole surface, so an endpoint is predictable from the
resource it addresses:

- **A path is nouns** — plural, kebab-case, one resource per segment. An action
  is a POST to the collection it creates (`POST .../scans` starts a scan,
  `POST .../deliveries` opens a PR). Where something is a genuine RPC with no
  resource to create, the verb is the *last* segment, never before an id.
- **A path parameter is named for what it identifies** — `{scan_id}`,
  `{finding_id}` — and comes before anything scoped to it. These names are not
  cosmetic: `ORG_RESOLVERS` in `api/router.py` is keyed by them, and an org-role
  route whose parameter is not in that dict fails at import.
- **State changes are `PATCH` on the resource** with a JSON body, answering with
  the resource's own `*Public` schema. No `/toggle` sub-path, no `enabled` query
  parameter, no ad-hoc `dict[str, str | bool]`.
- **One tag per engine or top-level resource**, because the tag becomes a service
  class in the generated client.

Each engine owns one namespace, with the same sub-collections under it:

```
/{engine}/{targets}                 /terraform/roots, /docker/targets,
                                    /cloud/accounts, /workflow/files
/{engine}/{targets}/{id}/scans      GET history, POST to start one
/{engine}/{targets}/{id}/findings
/{engine}/{targets}/{id}/files
/{engine}/{targets}/{id}/fixes      GET them, POST to generate them
/{engine}/{targets}/{id}/deliveries POST to open a PR for the ready fixes
/{engine}/scans|findings|fixes      cross-target reads, and single-item actions
```

An engine fills in only what it has — Cloud has no files or fixes, Docker adds
`/runtime-findings` — but it never spells a shared concept differently. If a new
engine needs a word the others do not have, that is the signal to look again.

FastAPI matches in declaration order, so a literal segment must be declared
before the `{id}` pattern beside it or it is unreachable — and it fails as a 422
"not a valid UUID", which reads like a client bug. `tests/api/test_roles.py`
pins the ones that exist today.

## Changing the API

The frontend and Action clients are generated. After any change to a route or a
schema, run `scripts/generate-client.sh` and commit the result — a pre-commit
hook does it too. An empty diff there is the proof a refactor did not move the
API surface, and is worth checking deliberately.

## Tests

`backend/tests/fixtures/factories.py` builds orgs, repos, workflow files, rules,
scans, findings and fixes. Use it rather than writing another `_make_repo`.

Some tests patch a module-level name that a function imports lazily — the
deferral *is* the seam. `pyproject.toml`'s per-file `PLC0415` ignores say which
files those are and why, and hoisting one of those imports silently stops the
patch landing.

## Migrations

`backend/scripts/schema_snapshot.py` dumps an order-insensitive view of the
metadata. Take it before and after any model refactor that should not change
DDL: mixin adoption and pure renames must show no column differences. Every
migration needs a `downgrade` that has actually been run.
