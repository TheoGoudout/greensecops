# "Before" example: a managed Postgres instance wired up quickly for an app.
# GreenSecOps flags it for storage that isn't encrypted at rest and for the
# instance carrying no cost/ownership tags. See expected.yaml.

provider "aws" {
  region = var.region
}

resource "aws_db_subnet_group" "postgres" {
  name       = "${var.name}-postgres"
  subnet_ids = var.subnet_ids
}

resource "aws_db_instance" "postgres" {
  identifier           = "${var.name}-postgres"
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.t3.medium"
  allocated_storage    = 20
  username             = "app"
  password             = var.db_password
  db_subnet_group_name = aws_db_subnet_group.postgres.name
  skip_final_snapshot  = true

  # No `storage_encrypted = true`: the database's data at rest is unencrypted.
  # No `tags = {}`: cost and ownership can't be attributed.
}
