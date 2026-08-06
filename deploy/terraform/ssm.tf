# The configuration contract between Terraform and Ansible.
#
# Two halves, because they have different owners and different blast radii:
#
#   /config/*  Written by Terraform. Everything derivable from the
#              infrastructure itself — endpoints, hostnames, bucket names.
#              Readable by every instance role. Changing one is a terraform
#              apply followed by a deploy.
#
#   /config/{IMAGE_TAG,PREVIOUS_IMAGE_TAG}
#              Declared here, then owned by the deploy pipeline. See the
#              dedicated resources at the bottom of this file.
#
#   /secret/*  Declared here with a placeholder and seeded out of band with
#              `aws ssm put-parameter --overwrite`. `ignore_changes` on the
#              value means Terraform never reads back, overwrites, or stores
#              the real secret — nothing sensitive reaches the state file.
#              Readable only by the roles that run application code.
#
# Ansible fetches the whole tree on each host with the instance's own role and
# renders it into /opt/greensecops/.env. Names map one-to-one onto the settings
# in backend/app/core/config.py, so the list below and .env.example describe the
# same variables.

locals {
  # Values Terraform knows because it built the thing they point at.
  config_parameters = {
    ENVIRONMENT  = var.environment
    PROJECT_NAME = "GreenSecOps"
    ECR_REGISTRY = var.ecr_registry
    AWS_REGION   = var.aws_region

    # Hosts and URLs. The backend derives the GitHub OAuth callback from
    # FRONTEND_HOST, so this is also what the OAuth app must be configured with.
    FRONTEND_HOST        = local.urls.frontend
    BACKEND_HOST         = local.urls.backend
    DOCS_URL             = local.urls.docs
    MARKETING_URL        = local.urls.landing
    BACKEND_CORS_ORIGINS = local.urls.frontend

    # Data tier. Where these point depends on the topology: at RDS and
    # ElastiCache when the data tier is managed, at container names on the
    # Docker network when it is not. POSTGRES_PASSWORD is absent in the managed
    # case on purpose — it lives in the RDS-managed Secrets Manager secret,
    # which Ansible reads separately; when self-hosted it is an ordinary
    # SecureString parameter alongside the others.
    POSTGRES_SERVER     = local.postgres_server
    POSTGRES_PORT       = local.postgres_port
    POSTGRES_DB         = module.data.postgres_database_name
    POSTGRES_USER       = module.data.postgres_username
    POSTGRES_SECRET_ARN = module.data.postgres_master_secret_arn

    REDIS_URL = local.redis_url

    # Behind the internal load balancer when OPA has its own hosts; over the
    # Docker network when it shares one with the backend.
    OPA_URL = local.opa_url

    CELERY_CONCURRENCY = tostring(var.celery_concurrency)

    ANSIBLE_TRANSFER_BUCKET = module.data.ansible_transfer_bucket_name

    # Tells Ansible which containers this deployment expects it to run, so the
    # rendered compose file includes db/redis exactly when Terraform did
    # not provision managed equivalents.
    SELF_HOSTED_DATA_TIER = tostring(!local.managed_database || !local.managed_cache)
  }

  # Declared, never populated by Terraform. The description is what an operator
  # sees in the console when working out what to put there.
  secret_parameters = {
    SECRET_KEY               = "Signs the API's JWTs. Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
    FIRST_SUPERUSER          = "Email address of the first superuser account."
    FIRST_SUPERUSER_PASSWORD = "Password for the first superuser account."

    GITHUB_APP_ID          = "Numeric ID of the GitHub App."
    GITHUB_APP_PRIVATE_KEY = "Full PEM content of the GitHub App's private key."
    GITHUB_WEBHOOK_SECRET  = "Shared secret verifying incoming GitHub webhooks. Must match the App's webhook secret field."
    GITHUB_CLIENT_ID       = "OAuth client ID for GitHub login."
    GITHUB_CLIENT_SECRET   = "OAuth client secret for GitHub login."
    GITHUB_APP_NAME        = "GitHub App slug, used to build the installation URL."

    DEFAULT_LLM_PROVIDER = "Which LLM provider generates fixes: openai, anthropic, gemini or ollama."
    DEFAULT_LLM_MODEL    = "Model name for the selected provider."
    OPENAI_API_KEY       = "OpenAI API key. Set at least one LLM provider key."
    ANTHROPIC_API_KEY    = "Anthropic API key. Set at least one LLM provider key."
    GOOGLE_API_KEY       = "Google Gemini API key. Set at least one LLM provider key."

    SMTP_HOST         = "SMTP server host. Email is disabled while this is unset."
    SMTP_USER         = "SMTP username."
    SMTP_PASSWORD     = "SMTP password."
    EMAILS_FROM_EMAIL = "Address outbound email is sent from."

    STRIPE_SECRET_KEY     = "Stripe API secret key. Billing is disabled while unset."
    STRIPE_WEBHOOK_SECRET = "Signing secret for Stripe webhooks."

    SENTRY_DSN = "Sentry DSN. Error reporting is disabled while unset."
  }

  # Only needed when PostgreSQL runs as a container: with RDS the password is
  # generated and rotated by AWS in Secrets Manager and never appears here.
  self_hosted_secret_parameters = local.managed_database ? {} : {
    POSTGRES_PASSWORD = "Password for the self-hosted PostgreSQL container. Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
  }

  # A value no running deployment would accept, so a parameter that was never
  # seeded fails loudly at deploy time instead of starting with a usable-looking
  # placeholder. The backend already refuses to boot on the literal
  # "changethis" in staging/production (app/core/config.py).
  unseeded_placeholder = "changethis"
}

resource "aws_ssm_parameter" "config" {
  for_each = local.config_parameters

  name        = "${local.ssm_prefix}/config/${each.key}"
  description = "Terraform-managed configuration value for ${local.name_prefix}."
  type        = "String"
  value       = each.value
  tier        = "Standard"
  overwrite   = true

  tags = merge(local.common_tags, {
    Name = "${local.ssm_prefix}/config/${each.key}"
  })
}

resource "aws_ssm_parameter" "secret" {
  for_each = merge(local.secret_parameters, local.self_hosted_secret_parameters)

  name        = "${local.ssm_prefix}/secret/${each.key}"
  description = each.value
  type        = "SecureString"
  key_id      = aws_kms_key.environment.arn
  value       = local.unseeded_placeholder
  tier        = "Standard"

  tags = merge(local.common_tags, {
    Name = "${local.ssm_prefix}/secret/${each.key}"
  })

  lifecycle {
    # The whole point: after creation the real value is written out of band and
    # Terraform must neither overwrite it nor pull it into state.
    ignore_changes = [value]
  }
}

# --------------------------------------------------------------------------
# Which image is deployed
# --------------------------------------------------------------------------
# Deliberately not part of config_parameters above. Those are written on every
# apply; these two are written by .github/workflows/deploy-reusable.yml, so
# `overwrite = true` would mean the next `terraform apply` silently reverted a
# deployment to whatever var.image_tag happened to say — and the change would
# only surface the next time an Auto Scaling group replaced an instance.
#
# var.image_tag therefore seeds the initial value and nothing more. To pin a
# tag from Terraform, remove the parameter from state and re-apply, or just
# deploy the tag you want.

resource "aws_ssm_parameter" "image_tag" {
  name        = "${local.ssm_prefix}/config/IMAGE_TAG"
  description = "Container image tag currently deployed. Written by the deploy pipeline."
  type        = "String"
  value       = var.image_tag
  tier        = "Standard"

  tags = merge(local.common_tags, {
    Name = "${local.ssm_prefix}/config/IMAGE_TAG"
  })

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "previous_image_tag" {
  name        = "${local.ssm_prefix}/config/PREVIOUS_IMAGE_TAG"
  description = "Tag that was deployed before the current one. What the rollback workflow deploys when given no explicit tag."
  type        = "String"
  value       = var.image_tag
  tier        = "Standard"

  tags = merge(local.common_tags, {
    Name = "${local.ssm_prefix}/config/PREVIOUS_IMAGE_TAG"
  })

  lifecycle {
    ignore_changes = [value]
  }
}
