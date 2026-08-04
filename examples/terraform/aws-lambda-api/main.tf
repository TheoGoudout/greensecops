# A serverless API written the way the AWS provider docs demonstrate each
# resource individually — which produces a function URL with no auth in front
# of it, an unencrypted work queue, and a database with neither backups nor
# deletion protection. Every one of those is the resource's own default, which
# is what makes this shape common.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source = "hashicorp/archive"
    }
  }

  backend "s3" {
    bucket       = "example-tfstate"
    key          = "lambda-api/terraform.tfstate"
    region       = "eu-west-1"
    encrypt      = true
    use_lockfile = true
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

resource "aws_lambda_function" "api" {
  function_name = "${var.project}-api"
  role          = aws_iam_role.api.arn
  handler       = "main.handler"
  runtime       = "python3.13"
  filename      = "build/api.zip"

  tags = local.common_tags
}

# No authorizer, no API Gateway, no WAF — the function itself is the whole
# security boundary, and it is billed per invocation.
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE"
}

resource "aws_iam_role" "api" {
  name = "${var.project}-api"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_sqs_queue" "jobs" {
  name = "${var.project}-jobs"

  tags = local.common_tags
}

resource "aws_db_instance" "main" {
  identifier        = "${var.project}-db"
  engine            = "postgres"
  engine_version    = "17.2"
  instance_class    = "db.t4g.micro"
  allocated_storage = 20
  username          = var.db_username
  password          = var.db_password

  storage_encrypted       = true
  publicly_accessible     = false
  backup_retention_period = 0

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.project}-api"
  retention_in_days = 30

  tags = local.common_tags
}
