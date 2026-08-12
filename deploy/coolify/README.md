# GreenSecOps on Coolify + Hetzner + Cloudflare

The cheapest credible way to run this project: **about €20/month**, versus ~$120
for the AWS `single_host` topology and ~$970 for `distributed`.

It works by removing things rather than shrinking them. Three of the four public
surfaces are static, so they leave the server entirely; object storage moves to
a provider that does not charge for egress; and the periodic scheduler folds
into the worker. What is left is five containers on one small server.

```
Cloudflare Workers (free) →  landing · dashboard · docs      static, CDN, unlimited bandwidth
Cloudflare R2 (~$1.50)    →  scan artifacts                  S3-compatible, zero egress fees
Hetzner CAX31 (€12.49)    →  backend · celery · opa
  or CPX31 (€13.60)          postgres · redis
  + backups, + volume
Raspberry Pi              →  Coolify control plane           deploys over SSH; not in the request path
```

| | Monthly |
|---|---|
| Hetzner CAX31 (ARM) or CPX31 (x86) — see availability below | €12.49–13.60 |
| Hetzner automated backups (20%) | €2.50 |
| Hetzner volume, 100 GB | €4.40 |
| Cloudflare R2, 100 GB stored | ~€1.40 |
| Cloudflare Workers, 3 static-asset Workers | free |
| GHCR image hosting | free |
| **Total** | **~€21–22** |

Egress is included on both Hetzner (20 TB/server) and R2 (zero), so this does
not grow with traffic the way a metered deployment does.

## About the Raspberry Pi and arm64

**Coolify running on an arm64 Pi does not restrict you to arm64 targets.**
Coolify's control plane connects to remote servers over SSH and, by default,
builds on the destination host — so a remote x86 server would build and run x86
images. The Pi's own architecture only matters if you enable Coolify's central
*build server* feature, or push images from the Pi to a registry.

It is moot here anyway, because **this setup builds nothing locally**.
`.github/workflows/images.yml` builds the backend and OPA images for *both*
architectures on GitHub's native runners and publishes them to GHCR as a
multi-architecture manifest; Coolify only pulls. The Pi never compiles
anything, which matters — `uv sync` on a Pi is slow enough to be annoying and
slow enough to time out a deploy.

**Hetzner's arm64 CAX line is their cheapest — when you can buy it.**

| Server | Arch | vCPU | RAM | Disk | Monthly |
|---|---|---|---|---|---|
| CAX21 | ARM Ampere | 4 | 8 GB | 80 GB | ~€6.49 |
| **CAX31** | ARM Ampere | **8** | **16 GB** | 160 GB | **~€12.49** |
| CX32 | Intel | 4 | 8 GB | 80 GB | ~€6.80 |
| **CPX31** | **AMD EPYC** | **4** | **8 GB** | 160 GB | **~€13.60** |
| CPX41 | AMD EPYC | 8 | 16 GB | 240 GB | ~€26.00 |
| CCX13 | AMD, dedicated | 2 | 8 GB | 80 GB | ~€13.50 |

### When CX and CAX are out of stock

They frequently are — Hetzner's cheapest shared lines sell out for weeks at a
time, and CAX in particular has been supply-constrained since launch. Stock is
per-location, so the first thing to try is another one. If you have a Hetzner
Cloud API token:

```bash
curl -sH "Authorization: Bearer $HCLOUD_TOKEN" \
  'https://api.hetzner.cloud/v1/server_types?per_page=50' \
| jq -r '.server_types[]
         | select(.name | test("^(cax|cx|cpx)"))
         | . as $t
         | .prices[]
         | select(.location | test("fsn1|nbg1|hel1"))
         | "\($t.name)\t\(.location)\t€\(.price_monthly.gross[0:5])"' \
| sort
```

That lists what exists and where, though not live stock. The console's create
page is the authoritative answer, and `hcloud server create` fails fast with
`resource_unavailable` when a type is sold out in a location — which is a
perfectly good way to poll.

In rough order of preference when neither CX nor CAX is available:

1. **CPX31 (~€13.60)** — AMD EPYC, x86. The closest substitute: same provider,
   same network, same volumes, same €. Half the vCPU of a CAX31 at the same
   RAM, which for this workload is not the binding constraint. **This is the
   recommendation** — the images are published for both architectures, so
   nothing about the deployment changes.
2. **CCX13 (~€13.50)** — dedicated vCPU rather than shared. Usually in stock
   when the shared lines are not, and the dedicated cores make the Celery
   workers noticeably more predictable.
3. **A different location.** Helsinki often has stock when Falkenstein does
   not. Latency differences are irrelevant here.
4. **Hetzner's server auction** (Robot, not Cloud) — dedicated hardware from
   about €35/month, absurd specs, effectively always available. Different
   product: no cloud volumes, no snapshots, no API-managed backups, so you
   would be arranging your own. Worth it only if you are staying a while.
5. **Another provider.** Netcup's ARM VPS line is comparable and often
   cheaper; OVH and Scaleway are both credible. None of this deployment is
   Hetzner-specific — Coolify only needs a server it can reach over SSH.

**This is why the images are multi-architecture.**
`.github/workflows/images.yml` publishes both amd64 and arm64 manifests, built
on native runners, so whichever server you manage to buy runs the same tag.
Moving between ARM and x86 later is a server rebuild, not a pipeline change.

**The Pi is not in the request path.** If it goes down you cannot deploy, but
the application keeps serving. That is a good failure mode for a control plane;
it does mean the Pi should not be the only thing holding your Coolify
configuration, so keep its backups somewhere else.

## Setting it up

### 1. Cloudflare — Workers, R2 and DNS

Nothing to create by hand: `pages.yml` deploys **six** Workers — a production
and a staging one for each surface — and `wrangler deploy` creates each on its
first run. The build output directory and 404 behaviour live in the
`wrangler.jsonc` beside the site it deploys (`landing/`, `frontend/`, `docs/`),
where production is the top-level configuration and staging is the `env.staging`
block:

| Surface | Production Worker | Staging Worker |
|---|---|---|
| landing | `greensecops-landing` | `greensecops-landing-staging` |
| dashboard | `greensecops-dashboard` | `greensecops-dashboard-staging` |
| docs | `greensecops-docs` | `greensecops-docs-staging` |

Your zone must be on Cloudflare nameservers. Unlike Pages, Workers cannot serve
a custom domain whose DNS is hosted elsewhere.

Create an R2 bucket for scan artifacts and an R2 API token scoped to it. R2's
S3 endpoint is `https://<account-id>.r2.cloudflarestorage.com`.

Add two repository **secrets** — `CLOUDFLARE_API_TOKEN` (Workers Scripts: Edit,
plus R2 if you use the same token) and `CLOUDFLARE_ACCOUNT_ID`. One account
serves both environments, so these stay at repository scope.

**The public URLs live in the repository**, one file per environment, at
[`deploy/cloudflare/env/`](../cloudflare/env/). Each declares a domain and three
subdomain labels, and the workflow derives the four URLs from them the same way
`deploy/terraform/locals.tf` does — so a hostname means the same thing on the
AWS and Cloudflare paths:

```
                deploy/cloudflare/env/production.env   deploy/cloudflare/env/staging.env
DOMAIN          greensecops.com                        staging.greensecops.com
landing         https://greensecops.com                https://staging.greensecops.com
dashboard       https://app.greensecops.com            https://app.staging.greensecops.com
API             https://api.greensecops.com            https://api.staging.greensecops.com
docs            https://docs.greensecops.com           https://docs.staging.greensecops.com
```

**These files are the only source.** No GitHub variable is consulted, which is a
correctness requirement rather than a preference: the `vars` context flattens
organisation, repository and environment scope into one namespace with no way to
tell them apart, so a repository-scoped `PUBLIC_API_URL` holding the production
hostname would be read by the *staging* build and quietly point it at the
production database. A fork edits the file. Nothing here is secret — every one
of these values is baked into the shipped JavaScript.

If you set the `PUBLIC_*` repository variables for an earlier version of this
workflow, they are now unread and can be deleted. That is tidying, not a fix —
nothing consults them.

Anything left empty or still `CHANGEME` **fails the build**. That is deliberate:
an unset variable renders as the empty string, and a dashboard built with
`VITE_API_URL=""` resolves every API call against its own Worker, which answers
`200` with `index.html` — a green pipeline publishing a site that is broken only
at runtime.

Point the apex, `app.` and `docs.` at their Workers as custom domains, and
`api.` at the Hetzner server's address. Do the same for the four staging
hostnames.

**One TLS caveat on the nested staging hostnames.** Cloudflare's free Universal
SSL covers `greensecops.com` and `*.greensecops.com` — one label deep, so
`app.staging.greensecops.com` is not on that certificate. It does not matter for
the three static surfaces: a Workers custom domain provisions its own
per-hostname certificate at any depth. It matters for `api.staging.`, which is
not a Worker — leave its DNS record **DNS-only (grey cloud)** so Coolify's proxy
terminates TLS with its own Let's Encrypt certificate, exactly as production's
`api.` already does. Proxying it instead needs Advanced Certificate Manager or
Total TLS, around $10/month.

**Staging needs its own GitHub App.** The backend derives the OAuth callback
from `FRONTEND_HOST`, and a GitHub App has a single webhook URL — production's
App cannot also point at `api.staging`. Staging's is already registered and its
client ID is in `staging.env`. Production's is not: `production.env` still holds
`CHANGEME`, so **a production dispatch fails at the config job until that App
exists and its client ID is filled in.** Staging and previews are unaffected.

Staging and pull-request previews serve the same pages as production, so
`pages-reusable.yml` writes a `robots.txt` and an `X-Robots-Tag: noindex` header
into every non-production build. Nothing but that stops them competing with the
real site in search results — there is no `robots.txt` in the repository.

### 2. Hetzner — the server

Create a **CAX31** in Falkenstein with Ubuntu 24.04, plus a 100 GB volume and
automated backups. Add your SSH key. Nothing else — Coolify installs what it
needs.

If CAX31 is out of stock, take a **CPX31** instead and change nothing else:
the images are published for both architectures. See
[when CX and CAX are out of stock](#when-cx-and-cax-are-out-of-stock).

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

**`TAG` means different things on the two resources.** Staging keeps
`TAG=latest` and tracks `main`, so every push redeploys it. On **production**,
`TAG` is owned by `.github/workflows/release-deploy.yml`: publishing a release
patches it to that release's tag over Coolify's API, alongside the resource's
git ref. Set it to `latest` once when you create the resource and then leave it
alone — editing it by hand pins production to whatever you typed until the next
release overwrites it.

### 5. Deploy

**Staging is automatic.** Push to `main`: `images.yml` publishes the backend and
OPA images to GHCR as `latest`, `pages.yml` publishes the three static sites to
the staging Workers, and Coolify's staging resource redeploys itself. Look at
staging.

**Production is two clicks**, and both halves move together:

1. Actions → **release** → *Run workflow*, pick a bump. It sets the version
   everywhere, closes off the accumulated release notes, tags `vX.Y.Z` and
   opens a **draft** GitHub release. Nothing is deployed — this is reviewable
   and undoable.
2. Review the draft, then **publish** it. That runs `release-deploy.yml`, which
   waits for the reviewer the `production` environment requires and then
   promotes the API and the static sites in that order.

The ordering is the point. The dashboard ships a generated OpenAPI client, so a
promoted dashboard talking to an unpromoted API breaks against a contract the
server has not shipped yet — `release-deploy.yml` deploys Coolify first and
blocks until Coolify reports the deployment finished, so the dashboard can
never get ahead. The reverse window still exists and is the tolerable one.

Sequencing is not a substitute for compatibility, though: browsers hold the old
dashboard bundle far longer than either deploy window, so a released API still
has to serve clients built against the previous release.

**What is running is visible in the dashboard footer** — the version, the
environment outside production, and a warning badge when the API reports a
different version from the dashboard.

If your GHCR packages are private, add a registry credential in Coolify with a
personal access token holding `read:packages`.

#### What the release workflows need

Three repository secrets, all for the Coolify half:

| Secret | What it is |
|---|---|
| `COOLIFY_URL` | Base URL of the Coolify control plane, reachable from GitHub Actions |
| `COOLIFY_TOKEN` | An API token with permission to update and deploy the resource |
| `COOLIFY_PRODUCTION_UUID` | The production resource's UUID |

The Pi is not in the request path, but it *is* in the deploy path — if its API
is not reachable from GitHub's runners, the Coolify job cannot run and
production has to be promoted from Coolify's UI instead.

`release.yml` reuses the existing `LATEST_CHANGES` PAT to push the release
commit and the tag. That has to be a PAT rather than `GITHUB_TOKEN`: a push
authenticated with `GITHUB_TOKEN` does not trigger other workflows, so
`images.yml` would never build the release images.

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
`pg_dump` off the host on a schedule if the data starts to matter:

```bash
docker compose exec -T db pg_dump -U "$POSTGRES_USER" greensecops \
  | gzip > "backups/$(date +%F).sql.gz"
```

Ship those somewhere off the box — any object store or backup target will do;
the deployment no longer provisions one of its own.

**The worker cannot be scaled.** `--beat` runs the periodic scheduler inside
the worker container, which is only safe with exactly one of them — two
embedded beats would each fire every scheduled task. To scale the workers,
split beat back into its own container as the root `compose.yml` has it, and
set `--concurrency` higher in the meantime.

**Static sites deploy separately from the API.** A release that changes both
the frontend and a backend contract still lands in two places at slightly
different times. Publishing a release now drives both from one workflow, in a
fixed order, and the dashboard job will not start until Coolify reports the API
deployment finished — so the pairing is enforced and the gap is always the
tolerable direction.

What is still not solved: **nothing rolls the API back when the dashboard
fails.** You are left with a new API and an old dashboard, which is survivable
but not the intended end state, and the run summary says so. Rolling back means
publishing the previous release, or repointing the Coolify resource by hand.

## Running other projects on the same server

Coolify is a multi-tenant platform and this stack does not fill a CPX31, so
putting other projects beside it is the obvious move. It is also where the
€13/month saving per project comes from, which is worth being honest about:
that is roughly what a second server costs, so isolation is cheap enough that
"we saved money" is rarely the argument that should decide it.

**What makes it safe is bounding things.** Every service here declares
`mem_limit`, `mem_reservation` and `cpu_shares` — see the comment at the top of
`compose.yml` for the reasoning. Without them the Celery worker is unbounded,
and when a scan fans out further than expected the kernel's OOM killer picks a
victim by score rather than by importance. That victim is usually a database,
and on a shared box it is as likely to be your neighbour's as this one's.

Steady state is about **1.5 GB reserved** against caps totalling ~5.5 GB, so on
8 GB there is real room for something else and a burst cannot claim all of it.

Four rules for anything you co-locate:

1. **Bound it the same way.** Limits on this stack only protect the host from
   *this* stack. An unbounded neighbour is the same problem pointed the other
   way.
2. **Never mount `/var/run/docker.sock`.** Plenty of self-hosted tooling asks
   for it — Portainer, Watchtower, Dozzle, CI runners. That mount is root on
   the host, and therefore root over this stack's GitHub App private key and
   its customers' AWS credentials. Use Coolify's own UI, which already has that
   access legitimately.
3. **One database per project.** Do not consolidate PostgreSQL to save RAM.
   Coolify defaults to a database per resource; keep it that way.
4. **Back up per project.** Hetzner's automated backups snapshot the whole
   volume, so restoring one project to last Tuesday restores all of them. The
   `pg_dump` to R2 above is what makes a single-project restore possible.

**The point at which to stop sharing** is not a resource threshold — it is the
first external user. This backend holds a GitHub App private key with write
access to customers' repositories and `AssumeRole` credentials into their AWS
accounts. Co-locating your own side projects risks your own things; co-locating
this one risks your customers'. That is also the first question on any security
questionnaire you will be sent, and "it shares a box with my other projects" is
not an answer you want to give.

Until then — pre-revenue, with only your own repositories connected — sharing
is a perfectly reasonable call.

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
