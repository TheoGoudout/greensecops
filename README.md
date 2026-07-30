# GreenSecOps

<a href="https://github.com/TheoGoudout/greensecops/actions?query=workflow%3A%22Test+Docker+Compose%22" target="_blank"><img src="https://github.com/TheoGoudout/greensecops/workflows/Test%20Docker%20Compose/badge.svg" alt="Test Docker Compose"></a>
<a href="https://github.com/TheoGoudout/greensecops/actions?query=workflow%3A%22Test+Backend%22" target="_blank"><img src="https://github.com/TheoGoudout/greensecops/workflows/Test%20Backend/badge.svg" alt="Test Backend"></a>
<a href="https://coverage-badge.samuelcolvin.workers.dev/redirect/TheoGoudout/greensecops" target="_blank"><img src="https://coverage-badge.samuelcolvin.workers.dev/TheoGoudout/greensecops.svg" alt="Coverage"></a>

GreenSecOps analyzes GitHub Actions workflows and automatically delivers fixes as pull requests. It evaluates every workflow file against a set of Rego rules across five axes — energy efficiency, reliability, security, performance, and maintainability — then uses an LLM to generate and open PRs with targeted improvements.

## Technology Stack

- ⚡ [**FastAPI**](https://fastapi.tiangolo.com) for the Python backend API.
  - 🧰 [SQLModel](https://sqlmodel.tiangolo.com) for the Python SQL database interactions (ORM).
  - 🔍 [Pydantic](https://docs.pydantic.dev), used by FastAPI, for the data validation and settings management.
  - 💾 [PostgreSQL](https://www.postgresql.org) as the SQL database.
  - 🔴 [Redis](https://redis.io) as the Celery broker and cache.
  - ⚙️ [Celery](https://docs.celeryq.dev) for async task processing (analysis, fix generation, fix delivery).
- 🔍 [Open Policy Agent (OPA)](https://www.openpolicyagent.org) for evaluating Rego rules against workflow files.
- 🤖 [LangChain](https://python.langchain.com) for LLM-powered fix generation, with support for OpenAI, Anthropic, Google Gemini, and Ollama.
- 🐙 GitHub App integration for webhook delivery, PR creation, and repository access.
- 🚀 [React](https://react.dev) for the frontend.
  - 💃 Using TypeScript, hooks, [Vite](https://vitejs.dev), and other parts of a modern frontend stack.
  - 🎨 [Tailwind CSS](https://tailwindcss.com) and [shadcn/ui](https://ui.shadcn.com) for the frontend components.
  - 🤖 An automatically generated frontend client.
  - 🧪 [Playwright](https://playwright.dev) for End-to-End testing.
  - 🦇 Dark mode support.
- 🐋 [Docker Compose](https://www.docker.com) for development and production.
- 🔒 Secure password hashing by default.
- 🔑 JWT and GitHub OAuth authentication.
- 📫 Email based password recovery.
- 📬 [Mailcatcher](https://mailcatcher.me) for local email testing during development.
- ✅ Tests with [Pytest](https://pytest.org).
- 🚢 Deployment instructions using Docker Compose, designed for [Coolify](https://coolify.io) with automatic HTTPS certificates.
- 🏭 CI/CD based on GitHub Actions.

## How It Works

1. **GitHub App installation** — users install the GitHub App on their organization or repository. A webhook event triggers repository synchronization and queues a static analysis job.
2. **Static analysis** — a Celery worker fetches the repository's workflow files and evaluates them through OPA, producing a list of issues across the five axes.
3. **Fix generation** — another Celery task passes the issues and workflow content to an LLM (via LangChain), which produces patched workflow YAML.
4. **Fix delivery** — the fix is delivered as a GitHub PR or an inline comment on the repository, depending on configuration.
5. **Dynamic analysis** (optional) — the companion [GitHub Action](./action/README.md) can be added to any workflow to capture runtime telemetry (CPU, RAM, disk, network) and send it back to GreenSecOps for enriched analysis.

## Configure

Copy `.env.example` to `.env` and fill in the required values. At minimum, set:

- `SECRET_KEY` — sign JWTs (`openssl rand -hex 32`)
- `FIRST_SUPERUSER_PASSWORD`
- `POSTGRES_PASSWORD`
- `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`
- `GITHUB_APP_NAME` — the GitHub App slug, used by the frontend to build the install URL
- At least one LLM provider key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or a running Ollama instance via `OLLAMA_BASE_URL`)

Read the [deployment.md](./deployment.md) docs for the full list of environment variables and secrets.

### Generate Secret Keys

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Or for hex secrets:

```bash
openssl rand -hex 32
```

## Backend Development

Backend docs: [backend/README.md](./backend/README.md).

## Frontend Development

Frontend docs: [frontend/README.md](./frontend/README.md).

## Deployment

Deployment docs: [deployment.md](./deployment.md).

To deploy on AWS with Terraform and Ansible instead of a single Docker host, see [deploy/README.md](./deploy/README.md).

## Development

General development docs: [development.md](./development.md).

This includes using Docker Compose, custom local domains, `.env` configurations, etc.

## Release Notes

Check the file [release-notes.md](./release-notes.md).

## License

GreenSecOps is licensed under the terms of the MIT license.
