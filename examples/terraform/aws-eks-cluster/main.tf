# An EKS cluster wired the way a first pass usually leaves it: the API server
# reachable from anywhere so kubectl works from a laptop, node logs kept
# forever, and the state file sitting on whoever ran apply. Exercises the
# control-plane and retention rules against a shape that is common in real
# repositories rather than a synthetic one.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  common_tags = {
    Team        = "platform"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_eks_cluster" "main" {
  name     = "${var.project}-cluster"
  role_arn = aws_iam_role.cluster.arn
  version  = "1.31"

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_public_access  = true
    endpoint_private_access = false
    public_access_cidrs     = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_iam_role" "cluster" {
  name = "${var.project}-cluster"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

# Attached to the cluster's nodes so they can pull images and write logs. The
# wildcard is the shortcut that gets a cluster working and then stays.
resource "aws_iam_role_policy" "node_access" {
  name = "${var.project}-node-access"
  role = aws_iam_role.cluster.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ecr:*"
      Resource = "*"
    }]
  })
}

resource "aws_cloudwatch_log_group" "cluster" {
  name = "/aws/eks/${var.project}-cluster/cluster"

  tags = local.common_tags
}

resource "aws_ecr_repository" "app" {
  name                 = "${var.project}/app"
  image_tag_mutability = "MUTABLE"

  tags = local.common_tags
}
