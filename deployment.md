# GreenSecOps - Deployment

You can deploy the project using Docker Compose to a remote server.

The production Compose file (`compose.yml`) is written for [Coolify](https://coolify.io/), a self-hostable deployment platform that builds the stack, injects secrets, and handles HTTPS and routing for the public-facing services. You can also run `compose.yml` by hand on any Docker host, as long as you provide the same variables yourself (see below).

## Preparation

* Have a remote server ready and available, with [Docker Engine](https://docs.docker.com/engine/install/) installed (and Coolify, if you use it).
* Configure the DNS records of your domain to point to the IP of the server.
* Plan a hostname for each public-facing service, e.g. `app.greensecops.example.com` (frontend dashboard), `api.greensecops.example.com` (backend), `docs.greensecops.example.com` (Sphinx docs), and `greensecops.example.com` (landing page).

## Coolify Magic Variables

`compose.yml` relies on [Coolify magic variables](https://coolify.io/docs/knowledge-base/docker/compose#coolify-magic-environment-variables): variables with a `SERVICE_` prefix that Coolify auto-generates at deploy time. The stack uses:

* `SERVICE_USER_POSTGRES`: Generated PostgreSQL user, passed to both the `db` and backend services as `POSTGRES_USER`.
* `SERVICE_PASSWORD_POSTGRES`: Generated PostgreSQL password, passed as `POSTGRES_PASSWORD`.
* `SERVICE_PASSWORD_64_SECRETKEY`: Generated 64-character secret, passed to the backend as `SECRET_KEY` (signs JWTs).
* `SERVICE_PASSWORD_FIRSTSUPERUSER`: Generated password for the first superuser account, passed as `FIRST_SUPERUSER_PASSWORD`.
* `SERVICE_URL_FRONTEND`: Public URL (scheme included) of the frontend dashboard. Used as the default for `FRONTEND_HOST` and `BACKEND_CORS_ORIGINS`, and as the landing page's `APP_URL`.
* `SERVICE_URL_BACKEND`: Public URL of the backend API. Used as the default for `BACKEND_HOST` and baked into the frontend build as `VITE_API_URL`.
* `SERVICE_URL_DOCS`: Public URL of the docs site. Used as the default for `DOCS_URL` and the docs image's `DOCS_BASE_URL` build arg.

**Deploying without Coolify:** export these seven variables in the shell (or a `.env` file next to `compose.yml`) before running `docker compose`. The CI workflow `.github/workflows/test-docker-compose.yml` shows a working set of test values.

## Environment Variables

Beyond the magic variables above, the stack is configured through ordinary environment variables. Coolify lets you set them in the resource's **Environment Variables** tab; on a plain Docker host, export them or put them in a `.env` file.

The backend reads its settings from `backend/app/core/config.py`; `.env.example` at the repository root documents the same list with local-development defaults.

### Generate secret keys

Some values must be secret keys. To generate one, run:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output and use it as the password / secret key. Run it again to generate another secure key. The backend refuses to start in `staging`/`production` with an empty `SECRET_KEY` or with any secret left at the placeholder value `changethis`.

### Required Environment Variables

* `ENVIRONMENT`: Deployment environment: `local` (development), `staging`, or `production`. `compose.yml` defaults it to `production`.
* `FIRST_SUPERUSER`: The email of the first superuser, this superuser will be the one that can create new users. Default: `admin@example.com`.
* `GITHUB_APP_ID`: The numeric ID of your GitHub App.
* `GITHUB_APP_PRIVATE_KEY`: The full PEM content of your GitHub App's private key.
* `GITHUB_WEBHOOK_SECRET`: The secret used to verify incoming webhook payloads from GitHub.
* `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`: OAuth credentials for GitHub login. The client ID is also baked into the frontend build as `VITE_GITHUB_OAUTH_CLIENT_ID`.
* `GITHUB_APP_NAME`: The GitHub App slug, baked into the frontend build as `VITE_GITHUB_APP_NAME` (used for the install URL `github.com/apps/<slug>/installations/new`).
* At least one LLM provider: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or a reachable Ollama instance via `OLLAMA_BASE_URL`.

Note: the GitHub OAuth callback URL is not configurable separately — the backend computes it as `${FRONTEND_HOST}/auth/github/callback`, so your GitHub OAuth App's "Authorization callback URL" must point at the frontend host.

### Optional Environment Variables

**Hosts and URLs**

* `FRONTEND_HOST`: Public URL of the frontend dashboard. Default: `${SERVICE_URL_FRONTEND}`.
* `BACKEND_HOST`: Public URL of the backend API. Default: `${SERVICE_URL_BACKEND}`.
* `GREENSECOPS_PUBLIC_URL`: Public backend URL embedded in generated customer workflow files. Empty by default, which falls back to `BACKEND_HOST`.
* `APP_URL`: Marketing/landing site URL used in PR messages. Default: `https://greensecops.io`.
* `DOCS_URL`: Public URL of the docs site, used for rule documentation links in PR messages. Default: `${SERVICE_URL_DOCS}`.
* `BACKEND_CORS_ORIGINS`: A list of allowed CORS origins separated by commas. Default: `${SERVICE_URL_FRONTEND}`.

**Branding**

* `PROJECT_NAME`: The name of the project, used in the API for the docs and emails. Default: `GreenSecOps`.
* `GITHUB_BOT_HANDLE`: The bot handle mentioned in PR messages. Default: `@greensecops`.
* `GITHUB_ACTION_REF`: The action reference written into generated customer workflows. Default: `greensecops/greensecops-action@v1`.

**Emails**

* `SMTP_HOST`: The SMTP server host to send emails, this would come from your email provider (E.g. Mailgun, Sparkpost, Sendgrid, etc). Emails are disabled if unset.
* `SMTP_USER`: The SMTP server user to send emails.
* `SMTP_PASSWORD`: The SMTP server password to send emails.
* `SMTP_PORT`: The SMTP server port. Default: `587`.
* `SMTP_TLS` / `SMTP_SSL`: Whether to use STARTTLS / implicit SSL. Defaults: `True` / `False`.
* `EMAILS_FROM_EMAIL`: The email account to send emails from. Default: `noreply@example.com`.
* `EMAILS_FROM_NAME`: The sender display name. Defaults to `PROJECT_NAME`.

**Database and infrastructure**

* `POSTGRES_PORT`: The port of the PostgreSQL server. Default: `5432`.
* `POSTGRES_DB`: The database name to use for this application. Default: `greensecops`.
* `POSTGRES_SERVER`, `REDIS_URL`, `OPA_URL`: Hardcoded by `compose.yml` to the in-network services (`db`, `redis://redis:6379/0`, `http://opa:8181`); only relevant when running the backend outside the Compose stack, where they default to `localhost`-based values.

**LLM configuration**

* `DEFAULT_LLM_PROVIDER`: Which LLM provider to use for fix generation. One of `openai`, `anthropic`, `gemini`, `ollama`. Default: `openai`.
* `DEFAULT_LLM_MODEL`: The model name for the selected provider. Default: `gpt-4o-mini`.
* `OLLAMA_BASE_URL`: Base URL of an Ollama instance, when using the `ollama` provider. Default: `http://localhost:11434`.
* `AI_PROVIDERS_CONFIG`: Path to a JSON file defining available providers and model lists. Defaults to the file bundled in the backend image.

**Billing (optional)**

* `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`: Stripe API credentials.
* `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_ULTIMATE`: Stripe price IDs for the subscription tiers.

**Observability (optional)**

* `SENTRY_DSN`: The DSN for Sentry, if you are using it.
* `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`: Enable LangSmith tracing for LLM calls.
* `LANGCHAIN_ENDPOINT`, `LANGCHAIN_PROJECT`: LangSmith endpoint and project name. Defaults: `https://api.smith.langchain.com`, `greensecops`.

## GitHub Actions Environment Variables

There are some environment variables only used by GitHub Actions (as repository secrets) that you can configure:

* `LATEST_CHANGES`: Used by the GitHub Action [latest-changes](https://github.com/tiangolo/latest-changes) to automatically add release notes based on the PRs merged. It's a personal access token, read the docs for details.
* `SMOKESHOW_AUTH_KEY`: Used to handle and publish the code coverage using [Smokeshow](https://github.com/samuelcolvin/smokeshow), follow their instructions to create a (free) Smokeshow key.

## Deploy with Docker Compose

With the environment variables in place (including the seven `SERVICE_*` variables if you are not using Coolify), you can deploy with Docker Compose:

```bash
docker compose -f compose.yml build
docker compose -f compose.yml up -d
```

For production you wouldn't want to have the overrides in `compose.override.yml`, that's why we explicitly specify `compose.yml` as the file to use.

Note that `compose.yml` does not publish any ports — in a Coolify deployment the platform's proxy routes the `SERVICE_URL_*` hostnames to the right containers and terminates HTTPS. On a plain Docker host you need to put your own reverse proxy in front of the `frontend`, `backend`, `landing`, and `docs` services.

## URLs

Replace `greensecops.example.com` with your domain. With the FQDNs suggested above:

Landing page: `https://greensecops.example.com`

Frontend (dashboard): `https://app.greensecops.example.com`

Sphinx docs: `https://docs.greensecops.example.com`

Backend API base URL: `https://api.greensecops.example.com`

Backend API docs: `https://api.greensecops.example.com/docs`

Adminer, Flower, and Mailcatcher are development-only services defined in `compose.override.yml` and are not part of the production stack (see [development.md](development.md) for the local URLs).
