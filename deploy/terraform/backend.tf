terraform {
  # Partial configuration: the bucket, key and region differ per environment
  # and are supplied at init time, so one root serves every environment.
  #
  #   terraform init -backend-config=env/production.backend.hcl
  #
  # The bucket itself is created by deploy/terraform/bootstrap.
  backend "s3" {}
}
