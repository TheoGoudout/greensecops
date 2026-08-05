package greensecops.cloud_aws.security.ecr_scan_on_push_disabled_test

import data.greensecops.cloud_aws.security.ecr_scan_on_push_disabled as no_scan
import rego.v1

_repo(scan_on_push) := {"ecr_repositories": [{
	"name": "api",
	"region": "eu-west-1",
	"tag_mutability": "IMMUTABLE",
	"scan_on_push": scan_on_push,
	"encryption_type": "KMS",
}]}

test_violation_when_scanning_is_off if {
	violations := no_scan.violations with input as _repo(false)
	count(violations) == 1
	some v in violations
	v.resource_id == "api"
}

test_no_violation_when_scanning_is_on if {
	violations := no_scan.violations with input as _repo(true)
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := no_scan.violations with input as {"ecr_repositories": []}
	count(violations) == 0
}

# The two ECR rules are independent — an immutable repository with no scanning
# is still reported here.
test_immutability_does_not_satisfy_this_rule if {
	violations := no_scan.violations with input as _repo(false)
	count(violations) == 1
}
