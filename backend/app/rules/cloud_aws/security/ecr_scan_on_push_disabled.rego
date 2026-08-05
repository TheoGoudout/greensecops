# METADATA
# title: ECR repository does not scan images on push
# description: An ECR repository does not scan images as they arrive, so a known-vulnerable base layer is discovered when somebody thinks to look rather than when it is introduced. Scan-on-push is the cheapest possible placement for that check — it runs once per image instead of once per deployment, it costs nothing, and it attributes the finding to the build that introduced it while the person who made the change still remembers why.
# custom:
#   severity: medium
#   detection: cloud_posture
#   examples:
#     bad: |
#       aws ecr create-repository --repository-name api
#     good: |
#       aws ecr create-repository --repository-name api \
#         --image-scanning-configuration scanOnPush=true
#     fix: |
#       Enable scan-on-push on the repository, or turn on registry-level enhanced scanning to cover every repository at once and keep re-scanning images as new advisories land — which push-time scanning alone does not do.
package greensecops.cloud_aws.security.ecr_scan_on_push_disabled

import rego.v1

violations contains violation if {
	some repo in input.ecr_repositories

	repo.scan_on_push == false

	violation := {
		"rule": "ecr_scan_on_push_disabled",
		"severity": "medium",
		"category": "security",
		"resource_type": "aws_ecr_repository",
		"resource_id": repo.name,
		"region": repo.region,
		"message": sprintf("Repository '%v' does not scan on push, so a vulnerable layer is found whenever somebody looks rather than when it lands.", [repo.name]),
	}
}
