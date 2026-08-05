package greensecops.cloud_aws.security.ecr_mutable_image_tags_test

import data.greensecops.cloud_aws.security.ecr_mutable_image_tags as mutable_tags
import rego.v1

_repo(mutability) := {"ecr_repositories": [{
	"name": "api",
	"region": "eu-west-1",
	"tag_mutability": mutability,
	"scan_on_push": true,
	"encryption_type": "KMS",
}]}

test_violation_for_a_mutable_repository if {
	violations := mutable_tags.violations with input as _repo("MUTABLE")
	count(violations) == 1
	some v in violations
	v.resource_id == "api"
	v.severity == "medium"
}

test_no_violation_for_an_immutable_repository if {
	violations := mutable_tags.violations with input as _repo("IMMUTABLE")
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := mutable_tags.violations with input as {"ecr_repositories": []}
	count(violations) == 0
}

test_each_repository_is_its_own_finding if {
	violations := mutable_tags.violations with input as {"ecr_repositories": [
		{"name": "api", "region": "eu-west-1", "tag_mutability": "MUTABLE"},
		{"name": "worker", "region": "eu-west-1", "tag_mutability": "MUTABLE"},
		{"name": "base", "region": "eu-west-1", "tag_mutability": "IMMUTABLE"},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
