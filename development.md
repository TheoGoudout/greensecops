# GreenSecOps - Development

## Docker Compose

* Start the local stack with Docker Compose:

```bash
docker compose watch
```

* Now you can open your browser and interact with these URLs:

Frontend (React dashboard): <http://localhost:5173>

Landing page: <http://localhost:3001>

Sphinx docs: <http://localhost:3002>

Backend API (JSON/OpenAPI): <http://localhost:8000>

Automatic interactive documentation with Swagger UI: <http://localhost:8000/docs>

Adminer, database web administration: <http://localhost:8080>

Flower, Celery task monitoring: <http://localhost:5555>

OPA, Open Policy Agent REST API: <http://localhost:8181>

**Note**: The first time you start your stack, it might take a minute for it to be ready. While the backend waits for the database to be ready and configures everything. You can check the logs to monitor it.

To check the logs, run (in another terminal):

```bash
docker compose logs
```

To check the logs of a specific service, add the name of the service, e.g.:

```bash
docker compose logs backend
```

## Mailcatcher

Mailcatcher is a simple SMTP server that catches all emails sent by the backend during local development. Instead of sending real emails, they are captured and displayed in a web interface.

This is useful for:

* Testing email functionality during development
* Verifying email content and formatting
* Debugging email-related functionality without sending real emails

The backend is automatically configured to use Mailcatcher when running with Docker Compose locally (SMTP on port 1025). All captured emails can be viewed at <http://localhost:1080>.

## Local Development

The Docker Compose files are configured so that each of the services is available in a different port in `localhost`.

For the backend and frontend, they use the same port that would be used by their local development server, so, the backend is at `http://localhost:8000` and the frontend at `http://localhost:5173`.

This way, you could turn off a Docker Compose service and start its local development service, and everything would keep working, because it all uses the same ports.

For example, you can stop that `frontend` service in the Docker Compose, in another terminal, run:

```bash
docker compose stop frontend
```

And then start the local frontend development server:

```bash
bun run dev
```

Or you could stop the `backend` Docker Compose service:

```bash
docker compose stop backend
```

And then you can run the local development server for the backend:

```bash
cd backend
fastapi dev app/main.py
```

## Local Ports vs Production Hostnames

When you start the Docker Compose stack locally, `compose.override.yml` publishes each service on a different `localhost` port (see the URL list above). Adminer, Flower, Mailcatcher, and the database are bound to `127.0.0.1` only and exist solely for development.

When deployed to production, `compose.yml` publishes no ports at all: each public-facing service (frontend, backend, landing, docs) gets its own hostname, and the deployment platform's reverse proxy routes traffic and terminates HTTPS. See the guide about [deployment](deployment.md) for how the hostnames are configured through the `SERVICE_URL_*` variables.

## Docker Compose files and env vars

There is a main `compose.yml` file with all the configurations that apply to the whole stack, it is used automatically by `docker compose`.

And there's also a `compose.override.yml` with overrides for development, for example to mount the source code as a volume. It is used automatically by `docker compose` to apply overrides on top of `compose.yml`.

These Docker Compose files use the `.env` file containing configurations to be injected as environment variables in the containers.

They also use some additional configurations taken from environment variables set in the scripts before calling the `docker compose` command.

After changing variables, make sure you restart the stack:

```bash
docker compose watch
```

## The .env file

The `.env` file is the one that contains all your configurations, generated keys and passwords, etc.

Depending on your workflow, you could want to exclude it from Git, for example if your project is public. In that case, you would have to make sure to set up a way for your CI tools to obtain it while building or deploying your project.

One way to do it could be to add each environment variable to your CI/CD system, and updating the `compose.yml` file to read that specific env var instead of reading the `.env` file.

## Pre-commits and code linting

we are using a tool called [prek](https://prek.j178.dev/) (modern alternative to [Pre-commit](https://pre-commit.com/)) for code linting and formatting.

When you install it, it runs right before making a commit in git. This way it ensures that the code is consistent and formatted even before it is committed.

You can find a file `.pre-commit-config.yaml` with configurations at the root of the project, holding workspace-wide hooks (file hygiene, OpenAPI client generation, deployment-config checks, commit message linting). `prek` also auto-discovers a `.pre-commit-config.yaml` in each of `backend/`, `docs/`, `frontend/`, `action/`, and `landing/` and runs their project-specific lint/format/typecheck hooks alongside it — no extra wiring needed, and each of those can also be run standalone from inside its own directory.

#### Hooks for the AWS deployment config

Four hooks cover `deploy/`, and only run when you touch it:

* `terraform-fmt` and `terraform-validate` run `terraform fmt -recursive` and `terraform validate` over `deploy/terraform/`. Both run in a `hashicorp/terraform` container — the same approach `backend/.pre-commit-config.yaml` takes for `opa fmt` and `opa check` — so you need Docker but not a local Terraform install.
* `deploy-terraform-opa` runs `scripts/validate_deploy_terraform.py`, which scans the deployment Terraform with GreenSecOps's own `iac_terraform` rules and **fails on any violation**. It needs the `opa` binary on your `PATH` (the same one `backend/`'s Rego hooks use) and Python with `python-hcl2`.
* `ansible-lint` lints `deploy/ansible/` at its `production` profile.

See [deploy/README.md](./deploy/README.md) for what these are guarding.

#### Install prek to run automatically

`prek` is already part of the dependencies of the project.

After having the `prek` tool installed and available, you need to "install" it in the local repository, so that it runs automatically before each commit.

Using `uv`, you could do it with (make sure you are inside `backend` folder):

```bash
❯ uv run prek install -f
prek installed at `../.git/hooks/pre-commit`
```

The `-f` flag forces the installation, in case there was already a `pre-commit` hook previously installed.

Now whenever you try to commit, e.g. with:

```bash
git commit
```

...prek will run and check and format the code you are about to commit, and will ask you to add that code (stage it) with git again before committing.

Then you can `git add` the modified/fixed files again and now you can commit.

#### Running prek hooks manually

you can also run `prek` manually on all the files, you can do it using `uv` with:

```bash
❯ uv run prek run --all-files
check for added large files..............................................Passed
check toml...............................................................Passed
check yaml...............................................................Passed
fix end of files.........................................................Passed
trim trailing whitespace.................................................Passed
ruff.....................................................................Passed
ruff-format..............................................................Passed
biome check..............................................................Passed
```

## URLs

Development URLs, for local development. In production each public-facing service gets its own hostname instead (see [deployment.md](deployment.md)).

Frontend (dashboard): <http://localhost:5173>

Landing page: <http://localhost:3001>

Sphinx docs: <http://localhost:3002>

Backend: <http://localhost:8000>

Automatic Interactive Docs (Swagger UI): <http://localhost:8000/docs>

Automatic Alternative Docs (ReDoc): <http://localhost:8000/redoc>

Adminer: <http://localhost:8080>

MailCatcher: <http://localhost:1080>

Flower (Celery): <http://localhost:5555>

OPA: <http://localhost:8181>

## Versioning and releases

The root `VERSION` file is the single source of truth. Every other place the
version appears is derived from it, and `scripts/validate_versions.py` — a
pre-commit hook and a CI job — fails if any of them drift:

| File | Why it carries the version |
|---|---|
| `frontend/package.json` | `vite.config.ts` bakes it into the bundle for the dashboard footer |
| `action/package.json` | the published GitHub Action's own version |
| `backend/pyproject.toml` | the `app` package |
| `docs/pyproject.toml` | the docs workspace member |
| `backend/app/__version__.py` | what `FastAPI(version=)` and `/api/v1/utils/version/` report |
| `frontend/src/client/core/OpenAPI.ts` | generated from the schema, which carries `info.version` |

Never edit these by hand. `scripts/bump_version.py` writes all of them and
regenerates `uv.lock`, which pins the `app` and `docs` workspace versions:

```bash
python scripts/bump_version.py 0.11.0        # explicit, including 0.11.0-rc1
python scripts/bump_version.py --bump minor  # computed from VERSION
```

`package.json`, `pyproject.toml` and `landing/package.json` at the root
deliberately carry **no** version — they are workspace roots and an unpublished
member. The validator asserts they stay that way.

### Cutting a release

Two steps, and the first one deploys nothing.

1. **Actions → release → Run workflow.** Pick `patch`/`minor`/`major`, or type
   an exact version to override it (this is how a `0.11.0-rc1` gets cut). The
   workflow bumps the version everywhere, renames the accumulated
   `## Latest Changes` section of `release-notes.md` to `## X.Y.Z (date)` and
   opens a fresh empty one, pushes the commit and the `vX.Y.Z` tag to `main`,
   and opens a **draft** GitHub release. Pushing the tag is what starts
   `images.yml` building `greensecops-{backend,opa}:vX.Y.Z`.

2. **Publish the draft.** That runs `release-deploy.yml`: it waits for the
   images, then — after the `production` environment's reviewer approves —
   deploys the API through Coolify's API and blocks until Coolify reports the
   deployment finished, then publishes the three static surfaces to Cloudflare.

Between the two steps nothing has been deployed, so a release that looks wrong
is undone by deleting the draft and the tag and reverting the commit.

`release-notes.md` itself is written by `latest-changes.yml` on every merged
pull request; you should not normally edit it by hand. It shares a `main-write`
concurrency group with `release.yml` so the two cannot race to push.

### Seeing what is deployed

The dashboard footer shows the version it was built with. Outside production it
also shows the short commit and an environment badge, because staging runs
`main` — which is almost always ahead of the last release, so the version alone
would not distinguish two staging builds.

The API reports its own version at `/api/v1/utils/version/`, and the footer
flags a mismatch. That matters because the dashboard and the API are promoted
through different platforms (Cloudflare Workers and Coolify), so a half-finished
promotion is otherwise invisible until it surfaces as a confusing error.
