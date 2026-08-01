# The managed replacements for the three stateful services compose.yml runs on
# the application host: PostgreSQL, Redis and MinIO. Everything here lives in
# the isolated subnet tier, which has no route to a NAT gateway.

# --------------------------------------------------------------------------
# PostgreSQL
# --------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  count      = var.create_managed_database ? 1 : 0
  name       = "${var.name_prefix}-postgres"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-postgres"
  })
}

resource "aws_db_parameter_group" "this" {
  count  = var.create_managed_database ? 1 : 0
  name   = "${var.name_prefix}-postgres"
  family = "postgres${var.postgres_version}"

  # The application connects over TLS; refusing plaintext at the server closes
  # the gap between "we configured TLS" and "TLS is required".
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-postgres"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "this" {
  count          = var.create_managed_database ? 1 : 0
  identifier     = "${var.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.postgres_version
  instance_class = var.postgres_instance_class

  db_name  = var.database_name
  username = var.database_username

  # RDS generates the master password and stores it in Secrets Manager itself,
  # rotating it on request. The alternative — a Terraform-managed password —
  # would write the credential into the state file in plaintext.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.kms_key_arn

  allocated_storage     = var.postgres_allocated_storage
  max_allocated_storage = var.postgres_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_subnet_group_name   = aws_db_subnet_group.this[0].name
  vpc_security_group_ids = [var.postgres_security_group_id]
  parameter_group_name   = aws_db_parameter_group.this[0].name
  publicly_accessible    = false
  multi_az               = var.postgres_multi_az

  backup_retention_period  = var.postgres_backup_retention_days
  backup_window            = "03:00-04:00"
  maintenance_window       = "sun:04:30-sun:05:30"
  copy_tags_to_snapshot    = true
  delete_automated_backups = false

  auto_minor_version_upgrade = true
  apply_immediately          = false

  performance_insights_enabled    = true
  performance_insights_kms_key_id = var.kms_key_arn
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring[0].arn
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  deletion_protection       = var.postgres_deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name_prefix}-postgres-final"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-postgres"
  })
}

data "aws_iam_policy_document" "rds_monitoring_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rds_monitoring" {
  count              = var.create_managed_database ? 1 : 0
  name               = "${var.name_prefix}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.rds_monitoring_assume.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  count = var.create_managed_database ? 1 : 0

  role       = aws_iam_role.rds_monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# RDS creates these log groups on first write with no retention; declaring them
# up front is the only way to stop the exported logs accumulating forever.
resource "aws_cloudwatch_log_group" "postgres" {
  for_each = var.create_managed_database ? toset(["postgresql", "upgrade"]) : toset([])

  name              = "/aws/rds/instance/${var.name_prefix}-postgres/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

# --------------------------------------------------------------------------
# Redis
# --------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "this" {
  count      = var.create_managed_cache ? 1 : 0
  name       = "${var.name_prefix}-redis"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-redis"
  })
}

resource "aws_elasticache_replication_group" "this" {
  count                = var.create_managed_cache ? 1 : 0
  replication_group_id = "${var.name_prefix}-redis"
  description          = "Celery broker, result backend and GitHub installation-token cache."

  engine         = "redis"
  engine_version = var.redis_version
  node_type      = var.redis_node_type
  port           = 6379

  num_cache_clusters         = var.redis_replica_count + 1
  automatic_failover_enabled = var.redis_replica_count > 0
  multi_az_enabled           = var.redis_replica_count > 0

  subnet_group_name  = aws_elasticache_subnet_group.this[0].name
  security_group_ids = [var.redis_security_group_id]

  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn

  # No AUTH token: it would have to be generated by Terraform and would then
  # live in the state file. Access is constrained by the security group and the
  # isolated subnet instead, and the wire is encrypted either way.
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"

  apply_immediately          = false
  auto_minor_version_upgrade = true
  maintenance_window         = "sun:05:30-sun:06:30"
  snapshot_retention_limit   = 7
  snapshot_window            = "02:00-03:00"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-redis"
  })
}

# --------------------------------------------------------------------------
# Object storage
# --------------------------------------------------------------------------

resource "aws_s3_bucket" "artifacts" {
  bucket        = var.artifact_bucket_name
  force_destroy = var.artifact_bucket_force_destroy

  tags = merge(var.tags, {
    Name = var.artifact_bucket_name
  })
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket     = aws_s3_bucket.artifacts.id
  depends_on = [aws_s3_bucket_versioning.artifacts]

  rule {
    id     = "expire-scan-artifacts"
    status = "Enabled"

    filter {}

    expiration {
      days = var.artifact_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}

data "aws_iam_policy_document" "artifacts_tls_only" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket     = aws_s3_bucket.artifacts.id
  policy     = data.aws_iam_policy_document.artifacts_tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

# --------------------------------------------------------------------------
# Ansible file transfer
# --------------------------------------------------------------------------
# amazon.aws.aws_ssm copies files through S3 rather than over the session
# channel, so the connection plugin needs a bucket of its own. Keeping it
# separate from the artifact bucket means the instance roles' write access to
# scratch space is not write access to customer scan data.

resource "aws_s3_bucket" "ansible_transfer" {
  bucket        = var.ansible_transfer_bucket_name
  force_destroy = true

  tags = merge(var.tags, {
    Name = var.ansible_transfer_bucket_name
  })
}

resource "aws_s3_bucket_versioning" "ansible_transfer" {
  bucket = aws_s3_bucket.ansible_transfer.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ansible_transfer" {
  bucket = aws_s3_bucket.ansible_transfer.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "ansible_transfer" {
  bucket = aws_s3_bucket.ansible_transfer.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "ansible_transfer" {
  bucket = aws_s3_bucket.ansible_transfer.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "ansible_transfer" {
  bucket     = aws_s3_bucket.ansible_transfer.id
  depends_on = [aws_s3_bucket_versioning.ansible_transfer]

  rule {
    id     = "expire-transfer-scratch"
    status = "Enabled"

    filter {}

    expiration {
      days = 1
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
