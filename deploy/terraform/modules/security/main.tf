# Every rule is an aws_vpc_security_group_{ingress,egress}_rule rather than an
# inline ingress/egress block. Inline blocks are authoritative for the whole
# group, so two Terraform runs that each add one rule silently delete the
# other's; the standalone resources are also the only form that supports
# per-rule tags and descriptions.
#
# Known gap, called out in deploy/README.md: the project's own
# `open_ingress_security_group` rule only inspects inline ingress blocks, so it
# does not see the 0.0.0.0/0 on the load balancer below. That ingress is
# intentional — the dashboard, API, docs and landing page are public — but the
# rule not reporting it is a limitation of the rule, not a property of this
# config.

locals {
  public_services   = { for role, svc in var.services : role => svc if svc.exposure == "public" }
  internal_services = { for role, svc in var.services : role => svc if svc.exposure == "internal" }

  # Cartesian product of "who may reach the data tier" × "which port", so a new
  # data store or a new client role is one list entry rather than a new block.
  data_clients = toset(var.data_client_roles)
}

# --------------------------------------------------------------------------
# Load balancers
# --------------------------------------------------------------------------

resource "aws_security_group" "public_alb" {
  name        = "${var.name_prefix}-public-alb"
  description = "Internet-facing load balancer for the dashboard, API, docs and landing page."
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-alb"
  })
}

resource "aws_vpc_security_group_ingress_rule" "public_alb_http" {
  for_each = toset(var.public_ingress_cidrs)

  security_group_id = aws_security_group.public_alb.id
  description       = "HTTP, redirected to HTTPS by the listener."
  cidr_ipv4         = each.key
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"

  tags = var.tags
}

resource "aws_vpc_security_group_ingress_rule" "public_alb_https" {
  for_each = toset(var.public_ingress_cidrs)

  security_group_id = aws_security_group.public_alb.id
  description       = "HTTPS from the public internet."
  cidr_ipv4         = each.key
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"

  tags = var.tags
}

resource "aws_vpc_security_group_egress_rule" "public_alb_to_targets" {
  security_group_id = aws_security_group.public_alb.id
  description       = "Forward requests to targets inside the VPC only."
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"

  tags = var.tags
}

resource "aws_security_group" "internal_alb" {
  name        = "${var.name_prefix}-internal-alb"
  description = "Internal load balancer fronting the OPA policy servers."
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-internal-alb"
  })
}

resource "aws_vpc_security_group_ingress_rule" "internal_alb_from_clients" {
  for_each = local.data_clients

  security_group_id            = aws_security_group.internal_alb.id
  description                  = "Policy evaluation requests from ${each.key}."
  referenced_security_group_id = aws_security_group.service[each.key].id
  from_port                    = var.services["opa"].port
  to_port                      = var.services["opa"].port
  ip_protocol                  = "tcp"

  tags = var.tags
}

resource "aws_vpc_security_group_egress_rule" "internal_alb_to_targets" {
  security_group_id = aws_security_group.internal_alb.id
  description       = "Forward requests to targets inside the VPC only."
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"

  tags = var.tags
}

# --------------------------------------------------------------------------
# Application instances — one group per role
# --------------------------------------------------------------------------

resource "aws_security_group" "service" {
  for_each = var.services

  name        = "${var.name_prefix}-${each.key}"
  description = "GreenSecOps ${each.key} instances."
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name               = "${var.name_prefix}-${each.key}"
    "greensecops:role" = each.key
  })
}

resource "aws_vpc_security_group_ingress_rule" "service_from_public_alb" {
  for_each = local.public_services

  security_group_id            = aws_security_group.service[each.key].id
  description                  = "Traffic from the internet-facing load balancer."
  referenced_security_group_id = aws_security_group.public_alb.id
  from_port                    = each.value.port
  to_port                      = each.value.port
  ip_protocol                  = "tcp"

  tags = var.tags
}

resource "aws_vpc_security_group_ingress_rule" "service_from_internal_alb" {
  for_each = local.internal_services

  security_group_id            = aws_security_group.service[each.key].id
  description                  = "Traffic from the internal load balancer."
  referenced_security_group_id = aws_security_group.internal_alb.id
  from_port                    = each.value.port
  to_port                      = each.value.port
  ip_protocol                  = "tcp"

  tags = var.tags
}

# Instances need to reach GitHub, the LLM providers, Stripe, SMTP and ECR, all
# of which are outside the VPC and none of which publish stable address ranges.
# Egress is therefore open; inbound is what the tiers above constrain.
resource "aws_vpc_security_group_egress_rule" "service_all" {
  for_each = var.services

  security_group_id = aws_security_group.service[each.key].id
  description       = "Outbound to AWS APIs, GitHub, LLM providers, Stripe and SMTP."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"

  tags = var.tags
}

# --------------------------------------------------------------------------
# Data tier
# --------------------------------------------------------------------------

resource "aws_security_group" "postgres" {
  name        = "${var.name_prefix}-postgres"
  description = "RDS PostgreSQL, reachable only from the application roles that hold a database session."
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-postgres"
  })
}

resource "aws_vpc_security_group_ingress_rule" "postgres_from_clients" {
  for_each = local.data_clients

  security_group_id            = aws_security_group.postgres.id
  description                  = "PostgreSQL sessions from ${each.key}."
  referenced_security_group_id = aws_security_group.service[each.key].id
  from_port                    = var.postgres_port
  to_port                      = var.postgres_port
  ip_protocol                  = "tcp"

  tags = var.tags
}

resource "aws_security_group" "redis" {
  name        = "${var.name_prefix}-redis"
  description = "ElastiCache Redis, the Celery broker and token cache."
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-redis"
  })
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_clients" {
  for_each = local.data_clients

  security_group_id            = aws_security_group.redis.id
  description                  = "Redis connections from ${each.key}."
  referenced_security_group_id = aws_security_group.service[each.key].id
  from_port                    = var.redis_port
  to_port                      = var.redis_port
  ip_protocol                  = "tcp"

  tags = var.tags
}
