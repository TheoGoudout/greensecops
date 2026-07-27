# "Before" example: a web tier that IS tagged (so it doesn't trip the tags
# rule) but is still insecure — a security group open to the whole internet, an
# unencrypted data volume, and AWS credentials hardcoded into user_data.
# See expected.yaml.

provider "aws" {
  region = var.region
}

locals {
  common_tags = {
    Team    = "platform"
    Service = "web"
  }
}

resource "aws_security_group" "web" {
  name        = "${var.name}-web"
  description = "Web tier security group"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH from anywhere"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_instance" "web" {
  ami           = var.ami_id
  instance_type = "t3.small"

  vpc_security_group_ids = [aws_security_group.web.id]

  # Long-lived credentials baked straight into the instance — the classic leak.
  user_data = <<-EOT
    #!/bin/bash
    export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
    aws s3 sync s3://${var.name}-assets /var/www/html
  EOT

  tags = local.common_tags
}

resource "aws_ebs_volume" "web_data" {
  availability_zone = var.availability_zone
  size              = 100

  # No `encrypted = true`: the volume's data at rest is unencrypted.

  tags = local.common_tags
}
