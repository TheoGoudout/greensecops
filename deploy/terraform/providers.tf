provider "aws" {
  region = var.aws_region

  # default_tags covers every resource, including the ones this config does not
  # name directly. It does not replace the literal `tags` each resource sets:
  # the project's own resource_missing_tags rule reads the configuration
  # statically and cannot see a provider-level default, and neither can anyone
  # reviewing a single file.
  default_tags {
    tags = local.common_tags
  }
}
