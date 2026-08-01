# The durable half of the single_host topology.
#
# When PostgreSQL, Redis and object storage run as containers rather than as
# RDS, ElastiCache and S3, their data has to outlive the instance — an Auto
# Scaling group replaces a failed host, and a root volume goes with it. This
# volume is created separately, tagged so cloud-init can find and attach it,
# and left alone when the instance is replaced.
#
# It is also the honest limit of the topology: one volume in one availability
# zone, with a daily crash-consistent snapshot as the only backup. Recovering
# from a lost zone means restoring a snapshot, not failing over. That is the
# trade the single_host topology makes, and the reason to move to
# `consolidated` — where RDS takes over with point-in-time recovery — before
# the data matters more than the saving.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

resource "aws_ebs_volume" "state" {
  availability_zone = var.availability_zone
  size              = var.size
  type              = "gp3"
  encrypted         = true
  kms_key_id        = var.kms_key_arn

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-state"

    # How the instance finds it: cloud-init looks up a volume in its own zone
    # carrying this tag, rather than being handed a volume ID it cannot know
    # at launch-template render time.
    "greensecops:state-volume" = var.name_prefix
  })

  lifecycle {
    # Every byte of application state in this topology lives here.
    prevent_destroy = true
  }
}

# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "dlm_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name               = "${var.name_prefix}-dlm-snapshots"
  description        = "Lets Data Lifecycle Manager snapshot the ${var.name_prefix} state volume."
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json

  tags = var.tags
}

data "aws_iam_policy_document" "dlm" {
  statement {
    sid    = "ManageSnapshots"
    effect = "Allow"
    actions = [
      "ec2:CreateSnapshot",
      "ec2:DeleteSnapshot",
      "ec2:DescribeVolumes",
      "ec2:DescribeSnapshots",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "TagSnapshots"
    effect    = "Allow"
    actions   = ["ec2:CreateTags"]
    resources = ["arn:${data.aws_partition.current.partition}:ec2:*::snapshot/*"]
  }

  statement {
    sid    = "UseVolumeKey"
    effect = "Allow"
    actions = [
      "kms:CreateGrant",
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:GenerateDataKeyWithoutPlaintext",
      "kms:ReEncryptFrom",
      "kms:ReEncryptTo",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "dlm" {
  name   = "snapshots"
  role   = aws_iam_role.dlm.id
  policy = data.aws_iam_policy_document.dlm.json
}

resource "aws_dlm_lifecycle_policy" "state" {
  description        = "Daily snapshots of the ${var.name_prefix} state volume."
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]

    target_tags = {
      "greensecops:state-volume" = var.name_prefix
    }

    schedule {
      name = "daily"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = [var.snapshot_hour_utc]
      }

      retain_rule {
        count = var.snapshot_retention
      }

      copy_tags = true

      tags_to_add = {
        SnapshotCreator = "dlm"
      }
    }
  }

  tags = var.tags
}
