# Two load balancers. The public one terminates TLS for all four hostnames and
# routes by Host header; the internal one is how the backend and the Celery
# workers reach OPA, replacing the `http://opa:8181` compose alias.

data "aws_elb_service_account" "current" {}

locals {
  # The landing page answers on the apex; the other three take a subdomain.
  # Ordered so the listener rules get stable priorities.
  subject_alternative_names = distinct([for host in values(var.hostnames) : host if host != var.domain_name])
}

# --------------------------------------------------------------------------
# Certificate
# --------------------------------------------------------------------------

resource "aws_acm_certificate" "this" {
  domain_name               = var.domain_name
  subject_alternative_names = local.subject_alternative_names
  validation_method         = "DNS"

  tags = merge(var.tags, {
    Name = var.domain_name
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.this.domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

# --------------------------------------------------------------------------
# Access logs
# --------------------------------------------------------------------------

resource "aws_s3_bucket" "access_logs" {
  bucket = var.access_log_bucket_name

  tags = merge(var.tags, {
    Name = var.access_log_bucket_name
  })
}

resource "aws_s3_bucket_versioning" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  # SSE-S3 rather than the environment KMS key: ELB access-log delivery does
  # not support a customer-managed key.
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket     = aws_s3_bucket.access_logs.id
  depends_on = [aws_s3_bucket_versioning.access_logs]

  rule {
    id     = "expire-access-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.access_log_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

data "aws_iam_policy_document" "access_logs" {
  # In most regions ELB delivers logs as logdelivery.elasticloadbalancing, but
  # the older regions still use a per-region account principal; granting both
  # is what makes this work everywhere.
  statement {
    sid    = "AllowElbAccountLogDelivery"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.current.arn]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/*"]
  }

  statement {
    sid    = "AllowLogDeliveryService"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/*"]
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.access_logs.arn,
      "${aws_s3_bucket.access_logs.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket     = aws_s3_bucket.access_logs.id
  policy     = data.aws_iam_policy_document.access_logs.json
  depends_on = [aws_s3_bucket_public_access_block.access_logs]
}

# --------------------------------------------------------------------------
# Public load balancer
# --------------------------------------------------------------------------

resource "aws_lb" "public" {
  name               = "${var.name_prefix}-public"
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.public_alb_security_group_id]

  enable_deletion_protection = var.deletion_protection
  drop_invalid_header_fields = true
  idle_timeout               = 120

  access_logs {
    bucket  = aws_s3_bucket.access_logs.id
    prefix  = "public"
    enabled = true
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public"
  })

  depends_on = [aws_s3_bucket_policy.access_logs]
}

resource "aws_lb_target_group" "public" {
  for_each = var.public_services

  name        = "${var.name_prefix}-${each.key}"
  port        = each.value.port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = each.value.health_check_path
    protocol            = "HTTP"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = merge(var.tags, {
    Name               = "${var.name_prefix}-${each.key}"
    "greensecops:role" = each.key
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.public.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }

  tags = var.tags
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.public.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = var.ssl_policy
  certificate_arn   = aws_acm_certificate_validation.this.certificate_arn

  # Anything that does not match a host rule below is not a hostname this
  # deployment serves; answering 404 is more honest than silently serving the
  # landing page for it.
  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Not found"
      status_code  = "404"
    }
  }

  tags = var.tags
}

resource "aws_lb_listener_rule" "host_routing" {
  for_each = var.public_services

  listener_arn = aws_lb_listener.https.arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.public[each.key].arn
  }

  condition {
    host_header {
      values = [var.hostnames[each.key]]
    }
  }

  tags = var.tags
}

# --------------------------------------------------------------------------
# Internal load balancer (OPA)
# --------------------------------------------------------------------------

resource "aws_lb" "internal" {
  count = var.internal_service == null ? 0 : 1

  name               = "${var.name_prefix}-internal"
  load_balancer_type = "application"
  internal           = true
  subnets            = var.private_subnet_ids
  security_groups    = [var.internal_alb_security_group_id]

  enable_deletion_protection = var.deletion_protection
  drop_invalid_header_fields = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-internal"
  })
}

resource "aws_lb_target_group" "internal" {
  count = var.internal_service == null ? 0 : 1

  name        = "${var.name_prefix}-opa"
  port        = var.internal_service.port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = var.internal_service.health_check_path
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = merge(var.tags, {
    Name               = "${var.name_prefix}-opa"
    "greensecops:role" = "opa"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# Plain HTTP: this listener is only reachable from the application security
# groups inside the VPC, and OPA serves no TLS of its own.
resource "aws_lb_listener" "internal" {
  count = var.internal_service == null ? 0 : 1

  load_balancer_arn = aws_lb.internal[0].arn
  port              = var.internal_service.port
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.internal[0].arn
  }

  tags = var.tags
}

# --------------------------------------------------------------------------
# DNS
# --------------------------------------------------------------------------

resource "aws_route53_record" "public" {
  for_each = var.hostnames

  zone_id = var.route53_zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = aws_lb.public.dns_name
    zone_id                = aws_lb.public.zone_id
    evaluate_target_health = true
  }
}
