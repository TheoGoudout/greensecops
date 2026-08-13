# GreenSecOps on AWS — Terraform + Ansible

Terraform provisions the infrastructure; Ansible configures the instances and runs the containers. This is an alternative to the Coolify/Compose deployment described in [deployment.md](../deployment.md), not a replacement — that path is still the simplest way to run the stack on a single host.

Applying this creates real, billed AWS resources. Nothing here runs automatically: CI only checks that the configuration is well-formed and passes the rule suite.

**If cost is the deciding factor, start with [deploy/coolify/](coolify/README.md) instead** — one small Hetzner server with the static sites on Cloudflare Workers, about €20/month against this path's ~$120 floor. It runs the same images and the same configuration contract, so moving here later is a migration rather than a rewrite.

## Topologies

The same deployment in three shapes. `topology` in the tfvars picks one; moving
between them is a variable change plus a data migration, not a rewrite.

| | `single_host` | `consolidated` | `distributed` |
|---|---|---|---|
| Hosts | 1 | 6 (3 groups × 2) | 13 (7 groups) |
| PostgreSQL | container | RDS | RDS Multi-AZ |
| Redis | container | ElastiCache | ElastiCache + replica |
| NAT gateways | 0 | 1 | 3 |
| PrivateLink endpoints | 0 | 0 | 5 × 3 AZ |
| Load balancers | 1 | 1 | 2 |
| Survives an instance failure | no | yes | yes |
| Survives an AZ failure | no | partly | yes |
| **Rough cost/month** | **~$120** | **~$330** | **~$970** |

**`single_host` is the default**, and is what `env/production.tfvars` ships
with. Every container runs on one box exactly as `compose.yml` does, including
PostgreSQL and Redis:

```
                     Route53 → ALB (HTTPS, host-header routing)
                                 │
                                 │  :8000 api.   :8081 app.
                                 │  :8082 apex   :8083 docs.
                                 ▼
                    ┌────────────────────────────┐
                    │  one EC2 instance          │
                    │                            │
                    │  backend   frontend        │
                    │  landing   docs    opa     │
                    │  celery-worker             │
                    │  celery-beat               │
                    │                            │
                    │  db  redis                 │
                    └─────────────┬──────────────┘
                                  │
                    persistent EBS volume, snapshotted daily
                    (/var/lib/greensecops)
```

The four public hostnames still resolve separately and are still routed by the
load balancer — they reach different host ports on the same box. That is what
makes the step up to `consolidated` a move rather than a redesign: the DNS,
certificates and routing do not change.

**No redundancy, by construction.** One instance, one availability zone, one
volume. An instance failure is an outage until the Auto Scaling group replaces
it and the volume reattaches; losing the zone means restoring a snapshot. The
[migration section](#migrating-between-topologies) says when that stops being
the right trade.

`consolidated` splits into three groups — static sites, API + policy, workers —
and moves PostgreSQL and Redis to managed services. `distributed` gives every
service its own group with an internal load balancer in front of OPA. Both are
described concretely in `env/examples/`.

### No public SSH

Instances have no SSH key. Ansible connects over **SSM Session Manager** using
the `amazon.aws.aws_ssm` connection plugin, and finds its hosts with the
`amazon.aws.aws_ec2` dynamic inventory keyed on the `greensecops:role` tag.
Access is therefore an IAM question in every topology.

In `single_host` and `consolidated` there are no NAT gateways for every subnet,
so the instances sit in public subnets with a public address for *egress* only —
inbound is closed by the security group, which admits the load balancer and
nothing else.

### Differences from the Compose deployment

| Compose | `single_host` | `consolidated` and above |
|---|---|---|
| `db` container | same | RDS PostgreSQL |
| `redis` container | same | ElastiCache |
| `opa` on the bridge | same | own group behind an internal LB |
| Coolify's proxy | ALB + ACM, host-header routing | same |
| `SERVICE_*` magic variables | SSM Parameter Store | same |

## Prerequisites

- An AWS account, and credentials with permission to create VPC, EC2, RDS, ElastiCache, S3, IAM, KMS, ACM, Route53 and CloudWatch resources.
- A **Route53 public hosted zone**, already delegated. This configuration creates records in it but does not own it.
- Locally: `terraform >= 1.10`, `ansible-core >= 2.19`, the AWS CLI v2, the Session Manager plugin, and Docker with `buildx` (for building images).
- A GitHub App, as described in [deployment.md](../deployment.md#required-environment-variables). Its webhook and callback URLs are known only after the first apply — step 6 below.

```bash
cd deploy/ansible && ansible-galaxy collection install -r requirements.yml -p collections
```

## Deploying

### 1. Bootstrap the account (once)

Creates the remote-state bucket, the KMS key that encrypts it, and the ECR repositories. Its own state is local, because it cannot store state in a bucket it has not created yet.

```bash
cd deploy/terraform/bootstrap
cp terraform.tfvars.example terraform.tfvars   # set a globally unique bucket name
terraform init
terraform apply
terraform output          # feed these into the next step
```

### 2. Configure the environment

Copy the outputs from step 1 into `env/<environment>.tfvars` (`ecr_registry`, `ecr_repository_arns`) and `env/<environment>.backend.hcl` (`bucket`, `kms_key_id`). Then set your domain, hosted zone ID, and three globally unique bucket names.

Both files ship with `CHANGEME` placeholders — every one has to go.

### 3. Apply

```bash
cd deploy/terraform
terraform init -backend-config=env/production.backend.hcl
terraform apply -var-file=env/production.tfvars
```

The first apply takes 20–30 minutes, most of it RDS and the ACM DNS validation.

### 4. Seed the secrets

Terraform declares every secret parameter with the placeholder `changethis` and `ignore_changes` on its value, so **no secret ever enters the state file**. Seed the real values out of band:

```bash
terraform output unseeded_secret_parameters      # the full list

aws ssm put-parameter --overwrite --type SecureString \
  --name /greensecops/production/secret/SECRET_KEY \
  --value "$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Required before the first deploy — Ansible refuses to proceed while any of these still holds its placeholder:

| Parameter | Notes |
|---|---|
| `SECRET_KEY` | Signs the API's JWTs. |
| `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD` | The first account that can create other users. |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` | Numeric ID and the full PEM. |
| `GITHUB_WEBHOOK_SECRET` | Must match the App's webhook secret field. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | OAuth credentials for GitHub login. |
| `GITHUB_APP_NAME` | The App slug, baked into the frontend build. |

On `single_host` one more is required, because the container has no managed
service to generate credentials for it:

| Parameter | Notes |
|---|---|
| `POSTGRES_PASSWORD` | Password for the PostgreSQL container. |

Optional; leave at the placeholder to keep the feature off: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` (at least one is needed for fix generation), `DEFAULT_LLM_PROVIDER`, `DEFAULT_LLM_MODEL`, `SMTP_*`, `EMAILS_FROM_EMAIL`, `STRIPE_*`, `SENTRY_DSN`.

The `/config/*` half of the tree is written by Terraform and needs no attention — endpoints, hostnames, bucket names and the image tag. Above `single_host`, `POSTGRES_PASSWORD` is in neither half: RDS generates and rotates it in Secrets Manager, and Ansible reads it at deploy time.

Every variable maps one-to-one onto a setting in `backend/app/core/config.py`; [`.env.example`](../.env.example) documents the same list with development defaults.

### 5. Set up the GitHub environments

This is what makes deploying a single click, and what puts production behind an approval.

In **Settings → Environments**, create `staging` and `production`. On each, set these **variables**:

| Variable | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `terraform output github_deploy_role_arn` |
| `AWS_REGION` | the environment's region |

The static surfaces need nothing here. Their public URLs are declared in [`deploy/cloudflare/env/`](cloudflare/env/) — one file per environment, derived the same way `deploy/terraform/locals.tf` derives them — and no GitHub variable is consulted for them at all, because `vars` cannot distinguish repository from environment scope and a repository-scoped production URL would otherwise be read by the staging build. See [`deploy/coolify/README.md`](coolify/README.md#1-cloudflare--workers-r2-and-dns).

On `production`, add **required reviewers**. That is the click: a run pauses until a reviewer approves, and only then can it obtain AWS credentials — the role's trust policy pins the OIDC subject to `repo:<owner>/<repo>:environment:production`, so an unapproved job is refused by AWS, not merely by GitHub. The same gate covers the static surfaces, which have no AWS role behind them: `pages.yml` will not publish to production until the run is approved.

Also set `production`'s **deployment branches and tags** rule to **Selected branches and tags**, with exactly two entries:

| Rule type | Pattern |
|---|---|
| Branch | `main` |
| Tag | `v*` |

This is the load-bearing guard on the Cloudflare side, where there is no AWS trust policy as a second line — without it, running `pages.yml` by hand from any branch could publish that branch to the live site.

The tag entry is what lets a release deploy at all. `release-deploy.yml` runs on a published release, so its ref is `refs/tags/vX.Y.Z` rather than a branch; with a branch-only rule the three publishing jobs in `pages-reusable.yml` **fail** — not skip — with *"not allowed to deploy to production due to environment protection rules"*, while the unbound `config` job succeeds, so the run goes half-green. The rule type is a per-entry dropdown: adding `v*` as a *branch* rule silently matches nothing.

**Protect the tags too.** A `v*` tag entry means anyone who can push such a tag can publish to production, and tag creation is not covered by branch protection. Add a repository ruleset targeting `refs/tags/v*` that restricts creation to the accounts that should be cutting releases — otherwise this widens the blast radius the rest of this section narrows.

No AWS keys are stored in GitHub. The workflow exchanges a short-lived OIDC token for a session at run time.

### 6. Build and deploy

From the Actions tab — **deploy** → *Run workflow* → pick an environment. Leave the tag empty to build the checked-out ref; give an existing tag to deploy that without rebuilding. See [Deploying and rolling back](#deploying-and-rolling-back) below.

By hand, if you prefer:

```bash
cd deploy/ansible
export GREENSECOPS_ENV=production AWS_REGION=eu-west-1

# Build the five images for arm64, push to ECR, record the tag.
ansible-playbook -i localhost, playbooks/build.yml -e image_tag=$(git rev-parse --short HEAD)

# Configure every instance and start its container.
ansible-playbook -i inventory/aws_ec2.yml playbooks/deploy.yml
```

`playbooks/site.yml` runs both.

The deploy is ordered: OPA first, then the backend (one instance at a time, running migrations once), then the workers, then the static sites. `docker compose up --wait` blocks on each container's own health check, so a broken image fails the playbook rather than the load balancer.

### 7. Point GitHub at the deployment

```bash
terraform output github_webhook_url         # → the App's webhook URL
terraform output github_oauth_callback_url  # → the OAuth App's callback URL
```

The callback URL is not separately configurable: the backend derives it from `FRONTEND_HOST`.

## Deploying and rolling back

Two workflows, both `workflow_dispatch`, both serialised on the same concurrency group so a deploy and a rollback can never race to set the tag.

**deploy** — pick an environment; leave the tag empty to build the checked-out ref and deploy it, or name a tag already in ECR to deploy that without rebuilding. Built images are tagged with the short commit SHA, so what is running traces back to a commit.

**rollback** — pick an environment; leave the tag empty to return to the previous release, or name any earlier tag to go further back. Nothing is rebuilt: the images are already in ECR, so a rollback is a pointer change plus a rolling restart, and takes about as long as the health checks.

The pointers live in Parameter Store:

| Parameter | Meaning |
|---|---|
| `/config/IMAGE_TAG` | what is deployed now |
| `/config/PREVIOUS_IMAGE_TAG` | what the rollback workflow returns to by default |

`PREVIOUS_IMAGE_TAG` is written *before* the rollout begins, so a deploy that fails half-way still leaves a correct rollback target. Both are declared by Terraform but carry `ignore_changes` on their value — the pipeline owns them, and `terraform apply` will not drag a deployment back to whatever `var.image_tag` says.

Each run ends with a summary naming the deployed tag, the previous tag, and how to undo it. A deploy that fails its post-rollout health check leaves the same instructions.

**Rolling back an infrastructure change is a separate job.** These workflows move application images only; `terraform apply` stays a deliberate local action. If a release changed both, revert the Terraform yourself.

## What it costs

Derived from the committed tfvars at `desired` capacity, eu-west-1, on-demand.
**Unit prices are approximate** — treat each line as ±15% and the totals as a
shape rather than a quote. Excluded throughout: internet data-transfer-out, and
LLM provider API spend, which for this product can exceed the infrastructure
bill on its own.

### `single_host` — the default

| Item | Monthly |
|---|---|
| 1 × `t4g.large` | $54 |
| Root volume, 30 GiB gp3 | $3 |
| State volume, 100 GiB gp3 | $9 |
| 14 daily snapshots | $8 |
| Application load balancer | $23 |
| Public IPv4 addresses (3) | $11 |
| S3 (artifacts, ALB logs, Ansible transfer) | $3 |
| CloudWatch logs, KMS, alarms, Route53, ECR | $9 |
| **Total** | **~$120** |

Staging, on `t4g.medium` with a 30 GiB volume and 3 snapshots, is about **$73**.

There is no NAT gateway, no PrivateLink endpoint, no RDS and no ElastiCache —
which is the whole reason this is a sixth of the distributed cost, not because
the compute is smaller.

### `consolidated`

| Item | Monthly |
|---|---|
| 6 instances (2 × small, 4 × medium) | $134 |
| EBS, 180 GiB gp3 | $16 |
| RDS `db.t4g.medium`, single-AZ, 50 GiB | $68 |
| ElastiCache `cache.t4g.micro` | $13 |
| NAT gateway (1) + data processing | $43 |
| Application load balancer + IPv4 | $33 |
| CloudWatch, KMS, S3, Route53, ECR | $20 |
| **Total** | **~$330** |

### `distributed`

| Item | Monthly |
|---|---|
| 13 instances | $228 |
| EBS, 390 GiB gp3 | $34 |
| RDS `db.m7g.large`, **Multi-AZ**, 100 GiB | $318 |
| ElastiCache `cache.t4g.small` × 2 | $53 |
| NAT gateways (3) + data processing | $115 |
| Load balancers (2) + LCU + IPv4 | $63 |
| **PrivateLink endpoints (5 × 3 AZ)** | **$120** |
| CloudWatch, KMS, S3, Route53, ECR | $35 |
| **Total** | **~$970** |

### Where the money goes

Above `single_host`, roughly a third of the bill buys no compute and no
storage: NAT gateways, PrivateLink ENIs and load balancer hours. PrivateLink in
particular is billed **per endpoint per availability zone** — five endpoints
across three zones is fifteen billed interfaces, $120/month, which is why
`interface_endpoints` is empty below the distributed topology and why even
there it is worth questioning. Add an endpoint only when the NAT
data-processing charge it displaces exceeds roughly $8/month.

The other structural lever is Multi-AZ RDS, which doubles the database instance
cost outright. `consolidated` deliberately starts single-AZ.

### Reducing it further

| Change | Saves | Costs you |
|---|---|---|
| Spot instances for the worker group | ~70% of that group | Interruptions; Celery already retries |
| 1-year Compute Savings Plan | ~30% of EC2 + RDS | A commitment |
| `interface_endpoints = []` on `distributed` | $120 | Slightly more NAT traffic |
| `nat_gateway_count = 1` on `distributed` | $70 | One AZ's egress is a single point of failure |
| CloudWatch retention 30 → 14 days | a few dollars | Shorter forensic window |

Already applied throughout: Graviton (ARM) instances, gp3 rather than gp2, and
the S3 gateway endpoint — which, unlike interface endpoints, is free.

### Other providers, for calibration

The same workload envelope elsewhere, at the `distributed` shape. Rough, and
less certain for the smaller providers:

| Platform | Monthly | Why it differs |
|---|---|---|
| AWS `distributed` | ~$970 | Meters NAT, PrivateLink and egress |
| GCP | ~$770 | Regional Cloud NAT, free Private Google Access, automatic sustained-use discounts |
| Azure | ~$940 | Free service endpoints, but pricier managed PostgreSQL HA |
| OVHcloud | ~$510 | No NAT charge, egress included |
| Scaleway | ~$510 | Cheap egress, no NAT charge |
| Oracle OCI | ~$400 | Cheapest ARM compute, 10 TB egress free, free NAT |

The gap is structural rather than a discount: providers that do not meter NAT,
per-AZ endpoints or egress are simply cheaper for this shape. It is also mostly
irrelevant at `single_host` — at ~$120/month the absolute saving from moving
providers is smaller than the cost of maintaining a second infrastructure
codebase, and the product is AWS-shaped at the feature level anyway
(`cloud_aws` rules, `aws_collector.py`).

## Migrating between topologies

Each step is a tfvars change plus, for the first one, a data migration. The
overrides to copy are in `env/examples/`.

### `single_host` → `consolidated`

**What should trigger it.** Any one of:

- The instance sits above ~70% CPU or memory at its daily peak, or the Celery
  queue depth no longer returns to zero between scans.
- An outage during instance replacement stops being acceptable — the gap is
  minutes, and the load balancer serves nothing for all of it.
- The database matters enough to want point-in-time recovery rather than a
  crash-consistent snapshot up to 24 hours old.
- You want to deploy without a brief interruption. Below `consolidated` there
  is one instance, so a rollout restarts it.

**What it costs.** About $210/month more, and one planned maintenance window.

**How.** The application data moves from containers to managed services, so
this is not a bare `apply`:

1. Apply with `managed_database = true` and `managed_cache = true` still on the
   `single_host` topology. RDS and ElastiCache are created alongside the running
   containers; nothing is cut over yet.
2. `pg_dump` from the container and restore into RDS. Redis needs nothing — it
   holds only the Celery broker and cached tokens, both regenerable.
3. Switch `topology = "consolidated"` and apply. The parameters flip to the
   managed endpoints, the groups split, and a NAT gateway appears.
4. Deploy. Confirm, then remove the state volume — it is `prevent_destroy`, so
   this means `terraform state rm` followed by deleting it by hand, which is
   deliberate friction on the only copy of the old database.

### `consolidated` → `distributed`

**What should trigger it.** Individual services needing to scale on their own
evidence — the Celery workers saturating while the API is idle, or OPA becoming
the request-path bottleneck. Not a general "we're bigger now": the consolidated
groups already scale, just together.

**What it costs.** About $640/month more, of which $120 is PrivateLink
endpoints you may not need and $175 is the Multi-AZ database upgrade.

**How.** No data migration — RDS and ElastiCache are already in place. Change
`topology`, `groups`, and the database sizing, then apply and deploy. The
internal load balancer appears in front of OPA and `OPA_URL` moves from the
Docker network to that endpoint automatically.

**Verify first.** Staging stays on `single_host`, so it does not exercise RDS,
ElastiCache or the internal load balancer. Bring a staging environment up on
the target topology before moving production.

## Operating

**Scaling.** `var.groups` in the tfvars sets `min`/`max`/`desired` per host group. On `single_host` there is one group pinned to one instance — scaling means a bigger `instance_type`, or the step up to `consolidated`. `celery-worker` target-tracks average CPU (`celery_worker_target_cpu`, default 60%) because its work is analysis; `opa` target-tracks requests per instance (`opa_target_requests_per_instance`, default 600/min) because policy evaluation is cheap per call but frequent. `celery-beat` is pinned to one instance — `PersistentScheduler` is not safe to run concurrently. Terraform ignores `desired_capacity` after creation, so an apply never undoes a scaling event.

**Rolling out.** Every group has a rolling instance refresh at `min_healthy_percentage = 100`, so capacity never dips during a replacement — except on `single_host`, where one instance means a rollout is a restart and a brief outage.

**Container limits.** `vars/services.yml` gives every container a `mem_limit`, a `mem_reservation` and a `cpu_shares` weight, rendered into the compose file on each host. The memory cap means a container that misbehaves dies alone rather than leaving the kernel's OOM killer to choose a victim by score — which on `single_host`, where PostgreSQL shares the box, is the difference between a restarted worker and a corrupted write. `cpu_shares` rather than a `cpus` ceiling, so a scan can use an otherwise idle instance and yields when it is not: data tier 2048, request path 1024, background work 512, static files 256. On `single_host` the caps total ~8.4 GB and the reservations ~2.2 GB, which fits `t4g.large` comfortably and `t4g.medium` (staging) with less room to spare. Raise `celery-worker` in step with `CELERY_CONCURRENCY` — budget roughly 500m per worker plus 500m of parent.

**Logs.** Container output goes straight to CloudWatch via the `awslogs` driver, under `/greensecops/greensecops-<env>/<role>` — so logs survive the instance, which matters when a group replaces one.

**Alarms.** Load-balancer 5xx, unhealthy hosts per target group, sustained CPU per group, and — where a managed data tier exists — database CPU and free storage plus Redis memory. On `single_host` the containers are covered by the group's CPU and disk alarms instead. All publish to the `alarm_topic_arn` SNS topic; `alarm_email` subscribes an address.

**Teardown.** `deletion_protection` must be set to `false` and applied before `terraform destroy` will remove the load balancers, and `postgres_deletion_protection` likewise above `single_host`. The artifact bucket needs `artifact_bucket_force_destroy = true` if it is not empty. The state volume carries `prevent_destroy`, so destroying a `single_host` environment means `terraform state rm module.state_volume[0].aws_ebs_volume.state` and then deleting it by hand — deliberate friction on the only copy of the database.

## Layout

```
deploy/
  terraform/
    bootstrap/          state bucket, KMS key, ECR repositories (local state)
    main.tf ssm.tf …    the environment root
    env/                per-environment tfvars and partial backend configs
      examples/         the overrides each topology step needs
    modules/
      network/          VPC, subnets, NAT, routes, VPC endpoints, flow logs
      security/         one security group per tier, rules as standalone resources
      iam/              per-role instance profiles and least-privilege policies
      data/             RDS, ElastiCache, artifact and transfer buckets
      edge/             ALBs, ACM certificate, listeners, Route53 records
      service/          reusable launch template + ASG, one per host group
      state_volume/     persistent EBS volume + snapshots, single_host only
      observability/    SNS topic and CloudWatch alarms
      cicd/             OIDC-trusted role GitHub Actions deploys with
  ansible/
    inventory/          aws_ec2 dynamic inventory over SSM
    tasks/              config resolution, imported as pre_tasks by every play
    vars/services.yml   what each role runs
    playbooks/          build.yml, deploy.yml, site.yml
    roles/              common, docker, cloudwatch_agent, greensecops_service
```

The workflows that drive all of this live in `.github/workflows/`: `deploy.yml`
and `rollback.yml` are the two dispatch entries, and `deploy-reusable.yml` holds
the mechanics they share.

## Checks

`deploy/` is covered by four checks, run by pre-commit and by CI (`.github/workflows/deploy-checks.yml` and the deploy step in `opa.yml`):

| Check | What it does |
|---|---|
| `terraform-fmt` | `terraform fmt -recursive` |
| `terraform-validate` | `terraform init -backend=false && terraform validate`, both roots |
| `deploy-terraform-opa` | **GreenSecOps's own rule suite against this Terraform, failing on any violation** |
| `ansible-lint` | `ansible-lint` at its `production` profile |

The Terraform hooks run in a `hashicorp/terraform` container, mirroring how `backend/.pre-commit-config.yaml` runs `opa fmt` — a contributor who only touches Python needs no new tooling.

The third one is the point. A product that sells Terraform scanning should have infrastructure its own rules pass, so `scripts/validate_deploy_terraform.py` merges every `.tf` file under `deploy/terraform/` exactly as production does and fails on **any** `iac_terraform` violation. That is stricter than `scripts/validate_terraform_examples.py`, whose fixtures assert an exact expected set because several exist precisely to demonstrate a finding.

Writing this configuration surfaced one real false positive, now fixed: `s3_bucket_missing_versioning` only recognised the deprecated inline `versioning` block, so every bucket written against an AWS provider v4 or later — where versioning is a separate `aws_s3_bucket_versioning` resource — was incorrectly flagged. `examples/terraform/aws-s3-split-config/` is the regression guard.

## Known gaps

**`open_ingress_security_group` does not see this configuration's public ingress.** The rule inspects inline `ingress` blocks inside `aws_security_group`; every rule here is a standalone `aws_vpc_security_group_ingress_rule`, which is the form AWS recommends and the only one supporting per-rule tags. The load balancer's `0.0.0.0/0` on 443 and 80 is therefore invisible to it.

That ingress is deliberate — the dashboard, API, docs and landing page are public, and `var.public_ingress_cidrs` exists to narrow it for a private deployment. But the rule *should* be able to see it and doesn't. Extending it to the standalone resource would need a waiver mechanism first, since a public web tier legitimately needs world ingress on 443 and the gate above admits no exceptions. Recorded here rather than left to be discovered.

**`vars/services.yml` duplicates part of `compose.yml`.** A split-host deployment cannot reuse a single-host Compose file: each service here runs alone and reaches PostgreSQL, Redis and OPA over the network rather than over a Compose bridge. The duplication is confined to one small file, but a command or health check changed in `compose.yml` has to be changed there too.

**`sts:AssumeRole` is unscoped** on the backend and worker roles. `app/services/cloud/aws_collector.py` assumes a role ARN each customer supplies at connect time, in an account this deployment has never seen, so the resource cannot be enumerated. The constraint is the trust direction: the customer's role must name this deployment's role ARN (`terraform output backend_role_arn`) *and* match a per-customer `ExternalId` before any call succeeds.
