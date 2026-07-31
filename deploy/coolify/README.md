# GreenSecOps on Coolify + Hetzner + Cloudflare

The cheapest credible way to run this project: **about €20/month**, versus ~$120
for the AWS `single_host` topology and ~$970 for `distributed`.

It works by removing things rather than shrinking them. Three of the four public
surfaces are static, so they leave the server entirely; object storage moves to
a provider that does not charge for egress; and the periodic scheduler folds
into the worker. What is left is five containers on one small ARM box.

```
Cloudflare Pages (free)   →  landing · dashboard · docs      static, CDN, unlimited bandwidth
Cloudflare R2 (~$1.50)    →  scan artifacts                  S3-compatible, zero egress fees
Hetzner CAX31 (€12.49)    →  backend · celery · opa
  + backups (€2.50)          postgres · redis
  + volume  (€4.40)
Raspberry Pi              →  Coolify control plane           deploys over SSH; not in the request path
```

| | Monthly |
|---|---|
| Hetzner CAX31 — 8 vCPU Ampere, 16 GB, 160 GB NVMe | €12.49 |
| Hetzner automated backups (20%) | €2.50 |
| Hetzner volume, 100 GB | €4.40 |
| Cloudflare R2, 100 GB stored | ~€1.40 |
| Cloudflare Pages, 3 projects | free |
| GHCR image hosting | free |
| **Total** | **~€21** |

Egress is included on both Hetzner (20 TB/server) and R2 (zero), so this does
not grow with traffic the way a metered deployment does.

## About the Raspberry Pi and arm64

**Coolify running on an arm64 Pi does not restrict you to arm64 targets.**
Coolify's control plane connects to remote servers over SSH and, by default,
builds on the destination host — so a remote x86 server would build and run x86
images. The Pi's own architecture only matters if you enable Coolify's central
*build server* feature, or push images from the Pi to a registry.

It is moot here anyway, because **this setup builds nothing locally**.
`.github/workflows/images.yml` builds the backend and OPA images on GitHub's
native arm64 runners and pushes them to GHCR; Coolify only pulls. The Pi never
compiles anything, which matters — `uv sync` on a Pi is slow enough to be
annoying and slow enough to time out a deploy.

**And Hetzner's arm64 line is their cheapest.** The CAX series is Ampere Altra:

| Server | vCPU | RAM | Disk | Monthly |
|---|---|---|---|---|
| CAX11 | 2 | 4 GB | 40 GB | ~€3.79 |
| CAX21 | 4 | 8 GB | 80 GB | ~€6.49 |
| **CAX31** | **8** | **16 GB** | **160 GB** | **~€12.49** |
| CAX41 | 16 | 32 GB | 320 GB | ~€24.49 |

CAX31 is the recommendation: 16 GB comfortably holds PostgreSQL, Redis and the
Python services with room for the Celery workers to do real work. CAX21 is
enough to start.

The project already targets arm64 — `opa/Dockerfile` pins the multi-arch
`-static` OPA variant precisely because the deployment host is ARM.

**One real constraint:** CAX is available in Falkenstein, Nuremberg and
Helsinki only. There is no US or Asia-Pacific CAX. If you need to host outside
the EU, Hetzner's x86 CPX line is the fallback, and the images workflow needs
`platforms: linux/amd64` (or both).

**The Pi is not in the request path.** If it goes down you cannot deploy, but
the application keeps serving. That is a good failure mode for a control plane;
it does mean the Pi should not be the only thing holding your Coolify
configuration, so keep its backups somewhere else.

## Setting it up

### 1. Cloudflare — Pages, R2 and DNS

Create three Pages projects — `greensecops-landing`, `greensecops-dashboard`,
`greensecops-docs`. They can start empty; the workflow deploys into them.

Create an R2 bucket for scan artifacts and an R2 API token scoped to it. R2's
S3 endpoint is `https://<account-id>.r2.cloudflarestorage.com`.

Add two repository **secrets** — `CLOUDFLARE_API_TOKEN` (Pages: Edit, plus R2
if you use the same token) and `CLOUDFLARE_ACCOUNT_ID` — and these repository
**variables**, which are baked into the shipped JavaScript and are not secret:

| Variable | Example |
|---|---|
| `PUBLIC_APP_URL` | `https://app.greensecops.com` |
| `PUBLIC_API_URL` | `https://api.greensecops.com` |
| `PUBLIC_DOCS_URL` | `https://docs.greensecops.com` |
| `PUBLIC_MARKETING_URL` | `https://greensecops.com` |
| `PUBLIC_GITHUB_CLIENT_ID` | your OAuth client ID |
| `PUBLIC_GITHUB_APP_NAME` | your GitHub App slug |
| `PUBLIC_SUPPORT_EMAIL` … `PUBLIC_PRIVACY_EMAIL` | contact addresses |

Point the apex, `app.` and `docs.` at their Pages projects as custom domains,
and `api.` at the Hetzner server's address.

### 2. Hetzner — the server

Create a **CAX31** in Falkenstein with Ubuntu 24.04, plus a 100 GB volume and
automated backups. Add your SSH key. Nothing else — Coolify installs what it
needs.

### 3. Coolify — connect the server

On the Pi, add the Hetzner box under **Servers → Add**, with its address and
your SSH key. Coolify validates the connection and installs Docker.

Then create a **Docker Compose** resource pointing at this repository with
`deploy/coolify/compose.yml` as the compose file, and set the destination to
the Hetzner server rather than the Pi.

### 4. Configure

Coolify generates the `SERVICE_*` magic variables described in
[deployment.md](../../deployment.md#coolify-magic-variables). Set the rest in
the resource's **Environment Variables** tab:

```
IMAGE_REGISTRY=ghcr.io/theogoudout
TAG=latest

SERVICE_URL_BACKEND=https://api.greensecops.com
SERVICE_URL_FRONTEND=https://app.greensecops.com
MARKETING_URL=https://greensecops.com
DOCS_URL=https://docs.greensecops.com

R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
S3_BUCKET=greensecops-artifacts

GITHUB_APP_ID=...
GITHUB_APP_PRIVATE_KEY=...
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_APP_NAME=...
OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY / GOOGLE_API_KEY
FIRST_SUPERUSER=you@example.com
CELERY_CONCURRENCY=2
```

Only `api.` needs a domain in Coolify — set it on the `backend` service so
Coolify's proxy terminates TLS and routes to it. The other three hostnames are
Cloudflare's.

### 5. Deploy

Push to `main`. `images.yml` publishes the backend and OPA images to GHCR and
`pages.yml` publishes the three static sites. Then hit **Deploy** in Coolify,
which pulls the new images and restarts the stack.

If your GHCR packages are private, add a registry credential in Coolify with a
personal access token holding `read:packages`.

### 6. Point GitHub at it

The GitHub App's webhook URL is `https://api.greensecops.com/api/v1/webhooks/github`,
and the OAuth callback is `https://app.greensecops.com/auth/github/callback` —
the backend derives the latter from `FRONTEND_HOST`, so it is not separately
configurable.

## What this trades away

**No redundancy.** One server. An outage is an outage, and a failed disk means
restoring a Hetzner backup. That is the deal at €20/month, and it is a
perfectly reasonable deal before there is revenue to protect.

**You are the ops team.** Nobody is paged but you. PostgreSQL backups are
Hetzner's whole-volume snapshots, not point-in-time recovery — take a
`pg_dump` to R2 on a schedule if the data starts to matter:

```bash
docker compose exec -T db pg_dump -U "$POSTGRES_USER" greensecops \
  | gzip | aws s3 cp - "s3://greensecops-artifacts/backups/$(date +%F).sql.gz" \
      --endpoint-url "$R2_ENDPOINT_URL"
```

**The worker cannot be scaled.** `--beat` runs the periodic scheduler inside
the worker container, which is only safe with exactly one of them — two
embedded beats would each fire every scheduled task. To scale the workers,
split beat back into its own container as the root `compose.yml` has it, and
set `--concurrency` higher in the meantime.

**Static sites deploy separately from the API.** A release that changes both
the frontend and a backend contract lands in two places at slightly different
times. For a change that breaks compatibility, deploy the backend first.

## Why OPA still runs as a server

The cost analysis suggested replacing the OPA container with `opa eval`
subprocesses, as `scripts/validate_deploy_terraform.py` does. **That is not
implemented, deliberately.**

It only saves money on platforms that bill per service — Render, Railway,
Fly.io. Here the container shares a box that is paid for regardless, so it
saves nothing, and it would cost real performance: `opa eval` reloads and
recompiles the whole rule bundle on every invocation, where the server holds it
compiled in memory across evaluations. On a scan that evaluates hundreds of
Terraform files that is the difference between milliseconds and seconds.

If you later move to a per-service platform, that is the moment to revisit it —
`app/services/opa/evaluator.py` is where it would change.

## When to leave

| Signal | Move to |
|---|---|
| Sustained CPU above ~70%, or the Celery queue never drains | A bigger CAX, then `deploy/terraform` on `single_host` |
| An outage during a deploy stops being acceptable | AWS `single_host` (~$120) — rolling replacement, one instance |
| A customer contract needs an SLA, or SOC 2 wants audited IaC | AWS `single_host` |
| Any single tier saturates its box | AWS `consolidated` (~$330) |

The AWS path in [`deploy/README.md`](../README.md) is the destination, not a
competitor: same containers, same images, same configuration contract. What
changes is who runs the database and how many boxes there are.
