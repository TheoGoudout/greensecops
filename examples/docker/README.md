# Docker examples

Realistic Dockerfiles and Compose files used to prove the `container_docker`
OPA rules fire (and stay quiet) on real-world configuration — the Docker
counterpart to [`examples/terraform/`](../terraform/README.md) and to the
GitHub Actions examples one level up (`examples/deploy.yml` /
`examples/deploy-insecure.yml`).

Each case is parsed and merged exactly as production does
(`backend/app/services/docker/merge.py::merge_docker_files`) and evaluated
against the live rule suite by
[`scripts/validate_docker_examples.py`](../../scripts/validate_docker_examples.py),
which runs in CI (`.github/workflows/opa.yml`). The set of rules a case trips
must match its `expected.yaml` **exactly**, so a rule that regresses (stops
firing) or starts producing a false positive fails the build.

## The cases

| Case | What it is for |
| --- | --- |
| `python-service-insecure/` | A deliberately bad Dockerfile + Compose pair. Trips most of the suite. |
| `node-api-insecure/` | A first-pass Node service — single stage, source copied before the install, a registry token copied in, TLS verification off. |
| `postgres-compose-exposed/` | A development stack with no Dockerfile: datastore ports published on every interface, dependencies with no health conditions. |
| `python-service-hardened/` | The same application, fixed. Must trip **nothing**. |
| `node-multistage/` | A correct multi-stage Node build — cached dependency layer, toolchain confined to the builder. Must trip nothing. |
| `compose-privileged-agent/` | Compose-only, no Dockerfile: proves a target containing just Compose files still reports. |

The two clean cases matter as much as the bad one. A rule that fires on
`python-service-hardened/` is producing noise on a file that is already
correct, and the build fails for it.

## Adding a new example (no code required)

1. Create a folder here, named for the scenario (e.g. `go-distroless/`).
2. Drop in any mix of Dockerfiles and Compose files. They are collected
   recursively and merged into one document, so a Compose file may reference a
   Dockerfile in a subdirectory via `build.dockerfile` exactly as it would in a
   real repository.
3. Add an `expected.yaml` listing the rule slugs the case should trip:

   ```yaml
   violations:
     - container_runs_as_root
     - compose_privileged_container
   ```

   Use `violations: []` for a clean case that must stay violation-free across
   the whole suite.

That's it — the validator auto-discovers every folder. No Python, workflow, or
manifest changes needed.

Recognised filenames are `Dockerfile`, `Dockerfile.*`, `*.Dockerfile`,
`Containerfile`, `compose.y[a]ml` and `docker-compose*.y[a]ml`; anything else in
the folder is ignored. A file that fails to parse fails the case loudly rather
than being silently skipped, so an example can never pass because it was not
actually scanned.

Note that Compose's runtime merge semantics are deliberately **not** modelled:
`compose.yml` and `compose.override.yml` are each evaluated as they appear on
disk, and `extends:` is not resolved. See the module docstring in
`backend/app/services/docker/merge.py`.

## Running it locally

```bash
OPA_BIN=/path/to/opa uv run --project backend python scripts/validate_docker_examples.py
```

`OPA_BIN` defaults to `opa` on `PATH`. The pinned version CI uses is in
[`.github/workflows/opa.yml`](../../.github/workflows/opa.yml), matching
`opa/Dockerfile`.
