# GreenSecOps on AWS — Terraform + Ansible

Terraform provisions the infrastructure; Ansible configures the instances and runs the containers. This is an alternative to the Coolify/Compose deployment described in [deployment.md](../deployment.md), not a replacement — that path is still the simplest way to run the stack on a single host.

Applying this creates real, billed AWS resources. Nothing here runs automatically: CI only checks that the configuration is well-formed and passes the rule suite.

## Architecture

```
                          Route53 (public hosted zone)
   example.com   app.   api.   docs.   →   ALB (public subnets, ACM certificate)
                                            │ routes by Host header
        ┌───────────────┬───────────────┬───┴───────────┬───────────────┐
        ▼               ▼               ▼               ▼               │
    landing ASG     frontend ASG    backend ASG      docs ASG           │ private
        │               │               │               │               │ subnets
        └───────────────┴───────┬───────┴───────────────┘               │
                                │                                       │
        celery-worker ASG (CPU-scaled)    celery-beat ASG (pinned to 1)  │
                                │                                       │
                     internal ALB → opa ASG (request-scaled) ───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   RDS PostgreSQL 18     ElastiCache Redis        S3 artifact bucket
   (isolated subnets)    (isolated subnets)       (VPC gateway endpoint)
```

Each of the seven containers in `compose.yml` gets its own Auto Scaling group. Three subnet tiers per availability zone: **public** (load balancer, NAT gateways), **private** (every instance), **isolated** (database and cache, with no route to a NAT gateway at all).

Differences from the Compose deployment:

| Compose | AWS |
|---|---|
| `db` container | RDS PostgreSQL, Multi-AZ, encrypted, automated backups |
| `redis` container | ElastiCache replication group, encrypted in transit and at rest |
| `minio` container | Real S3, reached with the instance role rather than a key pair |
| `opa` on the same bridge | Own instance group behind an internal load balancer |
| Coolify's proxy | ALB with an ACM certificate and Host-header routing |
| `SERVICE_*` magic variables | SSM Parameter Store, read by each instance |

### No public SSH

Instances have no public address and no SSH key. Ansible connects over **SSM Session Manager** using the `amazon.aws.aws_ssm` connection plugin, and finds its hosts with the `amazon.aws.aws_ec2` dynamic inventory keyed on the `greensecops:role` tag. Access is therefore an IAM question, and scaling a group from 2 to 8 needs no inventory change.

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

Optional; leave at the placeholder to keep the feature off: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` (at least one is needed for fix generation), `DEFAULT_LLM_PROVIDER`, `DEFAULT_LLM_MODEL`, `SMTP_*`, `EMAILS_FROM_EMAIL`, `STRIPE_*`, `SENTRY_DSN`.

The `/config/*` half of the tree is written by Terraform and needs no attention — endpoints, hostnames, bucket names and the image tag. `POSTGRES_PASSWORD` is in neither half: RDS generates and rotates it in Secrets Manager, and Ansible reads it at deploy time.

Every variable maps one-to-one onto a setting in `backend/app/core/config.py`; [`.env.example`](../.env.example) documents the same list with development defaults.

### 5. Build and deploy

```bash
cd deploy/ansible
export GREENSECOPS_ENV=production AWS_REGION=eu-west-1

# Build the five images for arm64, push to ECR, record the tag.
ansible-playbook -i localhost, playbooks/build.yml -e image_tag=$(git rev-parse --short HEAD)

# Configure every instance and start its container.
ansible-playbook -i inventory/aws_ec2.yml playbooks/deploy.yml
```

`playbooks/site.yml` runs both. Use `deploy.yml` alone to roll out an image already in ECR — a rollback is a tag change, not a rebuild.

The deploy is ordered: OPA first, then the backend (one instance at a time, running migrations once), then the workers, then the static sites. `docker compose up --wait` blocks on each container's own health check, so a broken image fails the playbook rather than the load balancer.

### 6. Point GitHub at the deployment

```bash
terraform output github_webhook_url         # → the App's webhook URL
terraform output github_oauth_callback_url  # → the OAuth App's callback URL
```

The callback URL is not separately configurable: the backend derives it from `FRONTEND_HOST`.

## Operating

**Scaling.** `var.services` in the tfvars sets `min`/`max`/`desired` per role. `celery-worker` target-tracks average CPU (`celery_worker_target_cpu`, default 60%) because its work is analysis; `opa` target-tracks requests per instance (`opa_target_requests_per_instance`, default 600/min) because policy evaluation is cheap per call but frequent. `celery-beat` is pinned to one instance — `PersistentScheduler` is not safe to run concurrently. Terraform ignores `desired_capacity` after creation, so an apply never undoes a scaling event.

**Rolling out.** Every group has a rolling instance refresh at `min_healthy_percentage = 100`, so capacity never dips during a replacement.

**Logs.** Container output goes straight to CloudWatch via the `awslogs` driver, under `/greensecops/greensecops-<env>/<role>` — so logs survive the instance, which matters when a group replaces one.

**Alarms.** Load-balancer 5xx, unhealthy hosts per target group, sustained CPU per group, database CPU and free storage, Redis memory. All publish to the `alarm_topic_arn` SNS topic; `alarm_email` subscribes an address.

**Rough cost.** The production defaults land around $700–900/month, dominated by the db.m7g.large Multi-AZ database (~$350), thirteen instances (~$250) and three NAT gateways (~$100). Staging with `single_nat_gateway = true`, `postgres_multi_az = false` and one instance per role is roughly $150–200.

**Teardown.** `postgres_deletion_protection` and `deletion_protection` must be set to `false` and applied before `terraform destroy` will remove the database and load balancers. The artifact bucket needs `artifact_bucket_force_destroy = true` if it is not empty.

## Layout

```
deploy/
  terraform/
    bootstrap/          state bucket, KMS key, ECR repositories (local state)
    main.tf ssm.tf …    the environment root
    env/                per-environment tfvars and partial backend configs
    modules/
      network/          VPC, subnets, NAT, routes, VPC endpoints, flow logs
      security/         one security group per tier, rules as standalone resources
      iam/              per-role instance profiles and least-privilege policies
      data/             RDS, ElastiCache, artifact and transfer buckets
      edge/             ALBs, ACM certificate, listeners, Route53 records
      service/          reusable launch template + ASG, instantiated seven times
      observability/    SNS topic and CloudWatch alarms
  ansible/
    inventory/          aws_ec2 dynamic inventory over SSM
    tasks/              config resolution, imported as pre_tasks by every play
    vars/services.yml   what each role runs
    playbooks/          build.yml, deploy.yml, site.yml
    roles/              common, docker, cloudwatch_agent, greensecops_service
```

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
