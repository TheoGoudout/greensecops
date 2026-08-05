package greensecops.cloud_aws.maintainability.eks_cluster_version_outdated_test

import data.greensecops.cloud_aws.maintainability.eks_cluster_version_outdated as outdated
import rego.v1

_cluster(version) := {"eks_clusters": [{
	"name": "prod",
	"region": "eu-west-1",
	"version": version,
	"endpoint_public_access": false,
	"public_access_cidrs": [],
	"enabled_log_types": ["audit"],
	"secrets_encrypted": true,
}]}

test_violation_for_a_version_past_standard_support if {
	violations := outdated.violations with input as _cluster("1.27")
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
	v.category == "maintainability"
}

test_no_violation_for_a_supported_version if {
	violations := outdated.violations with input as _cluster("1.31")
	count(violations) == 0
}

test_no_violation_exactly_at_the_supported_floor if {
	violations := outdated.violations with input as _cluster("1.30")
	count(violations) == 0
}

# Minor versions are compared numerically, not as strings — "1.9" must not sort
# above "1.30".
test_a_single_digit_minor_is_compared_numerically if {
	violations := outdated.violations with input as _cluster("1.9")
	count(violations) == 1
}

# A version string the API never returns must not crash the rule or fire.
test_no_violation_for_an_unparseable_version if {
	violations := outdated.violations with input as _cluster("latest")
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := outdated.violations with input as {"eks_clusters": []}
	count(violations) == 0
}

test_the_message_names_the_running_version if {
	violations := outdated.violations with input as _cluster("1.27")
	some v in violations
	contains(v.message, "1.27")
}
