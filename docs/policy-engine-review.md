# Policy engine review: is OPA/Rego still the right call?

Not part of the Sphinx build — like `state-machines.md`, this is a repo-local
decision record. It answers a question asked in August 2026: with 208 rules and
12.6k lines of Rego committed, does Open Policy Agent still earn its place?

**Verdict: keep Rego, retire the OPA server and the call shape.** The language
is load-bearing far beyond evaluation. The deployment shape — a separate HTTP
container, queried once per rule — is the part that has stopped paying for
itself.

## What is actually there

Measured from the tree, not estimated:

| | count |
|---|---|
| policy rules (`.rego`, non-test, non-lib) | 208 |
| rule unit tests (`_test.rego`) | 205 |
| lines of policy Rego | 12,658 |
| lines of Rego tests | 14,229 |
| domains under `app/rules/` | 7 + `lib/` |
| rules using `regex.*` | 49 |
| rules using `sprintf` | 192 |
| rules importing `data.greensecops.lib.*` | 38 |

The rule count understates the commitment. The `# METADATA` block is the single
source of truth for six consumers:

- `app/core/rule_registry.py` — seeds the `rule` table (title, description,
  severity, `severity_weight`, detection method)
- `app/core/rego_metadata.py` — the stdlib-only shared scanner
- `docs/ext/rego_autodoc.py` — the published rule catalog
- the four `scripts/validate_*_examples.py` validators
- `scripts/validate_deploy_terraform.py` / `validate_deploy_ansible.py` — the
  product's own deployment is gated on its own rules
- `scripts/regenerate_terraform_fixtures.py` — records violations so the pytest
  env, which has no `opa` binary, can replay them

`RuleDomain(dir_name)` derives the enum from the directory and
`_discover_policy_packages()` derives the evaluated package list from the
filesystem, so adding a rule is adding two files. Any migration must preserve
that property.

## Problem 1 — the evaluator fans out one HTTP POST per rule

`app/services/opa/evaluator.py::_evaluate_packages()` loops
`for package_path in package_paths` and POSTs `{"input": parsed}` to
`/v1/data/<package>` — sequentially, re-serializing the entire input document
every time.

- cloud scan: 43 POSTs, each carrying the full normalized AWS snapshot
- workflow scan: 61 POSTs of the parsed workflow
- Docker scan: 40 POSTs of the merged Dockerfile/Compose document

Cost is O(rules × document size), and it grows with every rule added.

`scripts/opa_eval.py` already knows better, using one aggregate query per
domain:

```
[v | v := data.greensecops.<domain>[_][_].violations[_]]
```

CI and production disagree about how to call the same engine, and production
has the worse half.

## Problem 2 — a container for a pure function

`opa/Dockerfile` ships a digest-pinned `openpolicyagent/opa:1.19.0-static` with
512m memory, a healthcheck, a build lane in `images.yml`, and an `OPA_URL` in
every deployment path (compose, Coolify, Ansible) — to compute
`document -> violations`. No state, no persistence, no egress.

Second-order cost: because it is out-of-process, the pytest environment asserts
Terraform rule behaviour against *recorded* violations, kept honest by a
separate CI job (`regenerate_terraform_fixtures.py --check`). A reasonable
workaround, not a design choice.

## What Rego buys that a rewrite would lose

- `opa check --strict` rejects unused arguments and unused assignments — the
  exact way a rule body silently stops testing what it reads. No Python linter
  has an equivalent for "this predicate is now vacuous".
- 205 rule tests running in seconds with no app import, no DB, no fixtures.
- Partial-set semantics (`violations contains v if {...}`) mean a rule that
  matches nothing is silent by construction. That is why the Ansible
  `input.files` envelope works and why cross-domain evaluation is safe.
- `# METADATA` is a first-class OPA convention, not a local invention.
- Rules are data. Nothing in a `.rego` file can import, open a socket or shell
  out. At 208 and growing, that containment matters.

## Recommended path

### Step 1 — collapse the fan-out

Small, self-contained, no migration, no rule changes.

- In `app/services/opa/evaluator.py`, replace the per-package loop with a
  single `POST /v1/query` per domain carrying
  `{"query": "[v | v := data.greensecops.<domain>[_][_].violations[_]]",
  "input": payload}`. `/v1/query` is preferred over a `/v1/data/<domain>`
  subtree read: it returns a flat list needing no client-side walk, and it
  matches `scripts/opa_eval.py::domain_query()` exactly — one shape for CI and
  production.
- Lift `domain_query()` somewhere both can import rather than writing a second
  copy.
- Keep `_discover_policy_packages()`. It stops driving evaluation but remains
  the check that every seeded rule is actually loaded.
- Preserve `OpaUnavailableError` semantics: an outage must still fail the scan
  rather than report a perfect score.
- `backend/tests/services/test_opa_evaluator.py` mocks per-package responses
  today and needs reshaping to the single-call form.

Expected effect: 43 round trips -> 1 on a cloud scan; the document is
serialized once instead of once per rule.

### Step 2 — evaluate in-process (decide separately)

Once step 1 lands the interface is a single query with one input, which is what
an embedded interpreter offers. In order of preference:

1. **Regorus** (`microsoft/regorus`) — Rust Rego interpreter with pyo3
   bindings. Keeps all 12.6k lines of Rego and all 205 tests unchanged.
   Verify first: the Python bindings are **not published to PyPI** (build with
   maturin), and it tracks OPA ~v1.2.0 while we pin 1.19.0 — so audit builtin
   coverage against the 49 regex rules and the `sprintf` / `object.get` /
   semver usage across the catalog.
2. **`opa eval` subprocess** — no new dependencies, and `scripts/opa_eval.py`
   proves the pattern. A process spawn per scan is wrong for a hot path but
   right for the pytest environment.
3. **OPA compiled to WASM** — official and in-process, but adds a build
   artifact to keep in step with the rules.

The prize is deleting `opa/Dockerfile`, its `images.yml` lane, the
compose/Coolify/Ansible service definitions and `OPA_URL` — and letting
`backend/tests/` evaluate rules directly, retiring the recorded Terraform
fixtures and the CI job that guards them.

Step 2 is **not** a prerequisite for step 1.

## Alternatives considered and rejected

- **Python predicate functions** — loses `opa check --strict`, loses
  rules-as-data, and requires reimplementing the METADATA pipeline for six
  consumers. A 12.6k-line rewrite buying debuggability available more cheaply
  by embedding the interpreter.
- **CUE** — good at "this document must conform", bad at "collect every
  violation with a line span and a message". Wrong shape for a findings engine.
- **CEL** — single-expression predicates; no partial-set collection, no
  per-rule metadata convention.
- **Semgrep / OpenGrep** — pattern-matches *source files*. Our engines evaluate
  *merged, normalized* documents (a Terraform root list-concatenated across
  files; Compose services correlated with the Dockerfiles they build). That
  correlation is the product and is invisible to a per-file matcher.
- **Off-the-shelf scanners** (Checkov, Trivy, zizmor, hadolint) — a product
  decision, not a DSL swap, and worth its own discussion: the differentiator is
  the grading model and the LLM fixes, not the rule bodies. But it trades one
  uniform vocabulary for four tools' divergent severities and IDs, which is
  what `CLAUDE.md`'s "one vocabulary" section exists to prevent.

## Verification for step 1

1. `opa check --strict backend/app/rules && opa test backend/app/rules` — the
   rules do not change, so this stays green untouched.
2. `backend/scripts/test.sh`, with `test_opa_evaluator.py` reshaped to the
   single-call mock plus the integration tests under `backend/tests/workers/`.
3. Parity, not just green: run every fixture in
   `backend/tests/fixtures/terraform/` through both call paths and diff the
   violation sets. They must be identical.
4. The four `scripts/validate_*_examples.py` validators — they go through
   `opa_eval.py`, so a shared `domain_query()` is exercised from both sides.
5. `python scripts/regenerate_terraform_fixtures.py --check` — unchanged output
   is the proof the refactor did not move rule behaviour.
