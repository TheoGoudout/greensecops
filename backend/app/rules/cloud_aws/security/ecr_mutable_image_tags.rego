# METADATA
# title: ECR repository allows tags to be overwritten
# description: An ECR repository permits an existing tag to be repointed at a new image. That makes a tag a moving reference rather than an identity, so the image a deployment pulled last week is not necessarily the image that tag names today — and if something turns out to be wrong with it, the evidence has already been overwritten. It is also the cleanest supply-chain attack available against a pipeline that deploys by tag, since replacing the artifact requires no change to any manifest anyone reviews.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ecr create-repository --repository-name api
#     good: |
#       aws ecr create-repository --repository-name api \
#         --image-tag-mutability IMMUTABLE
#     fix: |
#       Set the repository to IMMUTABLE and give every build a unique tag — the commit SHA is the usual choice. Where a floating tag like `latest` is genuinely wanted, keep it as a separate deployment-time lookup rather than as the thing the pipeline pushes over.
package greensecops.cloud_aws.security.ecr_mutable_image_tags

import rego.v1

violations contains violation if {
	some repo in input.ecr_repositories

	repo.tag_mutability == "MUTABLE"

	violation := {
		"rule": "ecr_mutable_image_tags",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_ecr_repository",
		"resource_id": repo.name,
		"region": repo.region,
		"message": sprintf("Repository '%v' allows tags to be overwritten, so a tag names whatever was pushed last rather than a fixed image.", [repo.name]),
	}
}
