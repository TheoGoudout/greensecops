# METADATA
# title: ECR repository allows tags to be overwritten
# description: An aws_ecr_repository leaves image_tag_mutability at MUTABLE, so pushing an existing tag replaces what it points at. Everything downstream that refers to the tag then silently gets different content — a rollback to a known-good tag can land on an image that is not the one that was known good, and an audit of what ran cannot be answered from the tag alone. It is the registry-side counterpart of the unpinned_base_image problem.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       resource "aws_ecr_repository" "app" {
#         name                 = "app"
#         image_tag_mutability = "MUTABLE"
#       }
#     good: |
#       resource "aws_ecr_repository" "app" {
#         name                 = "app"
#         image_tag_mutability = "IMMUTABLE"
#       }
#     fix: |
#       Set image_tag_mutability = "IMMUTABLE" so a tag always names the same image. Use a new tag per build (a commit SHA works well) rather than moving a shared one.
package greensecops.iac_terraform.security.ecr_mutable_image_tags

import rego.v1

violations contains violation if {
	some res in input.resource
	some name, repo in res.aws_ecr_repository
	object.get(repo, "image_tag_mutability", "MUTABLE") == "MUTABLE"
	violation := {
		"rule": "ecr_mutable_image_tags",
		"severity": "medium",
		"category": "security",
		"resource_address": sprintf("aws_ecr_repository.%v", [name]),
		"file_path": object.get(repo, "__tf_file", ""),
		"line_start": object.get(repo, "__start_line__", null),
		"line_end": object.get(repo, "__end_line__", null),
		"message": sprintf("ECR repository '%v' allows mutable tags, so a tag can be repointed at different content after anything downstream has started trusting it.", [name]),
	}
}
