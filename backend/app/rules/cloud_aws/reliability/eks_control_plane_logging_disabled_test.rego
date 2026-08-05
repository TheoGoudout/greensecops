package greensecops.cloud_aws.reliability.eks_control_plane_logging_disabled_test

import data.greensecops.cloud_aws.reliability.eks_control_plane_logging_disabled as no_audit
import rego.v1

_cluster(log_types) := {"eks_clusters": [{
	"name": "prod",
	"region": "eu-west-1",
	"version": "1.31",
	"endpoint_public_access": false,
	"public_access_cidrs": [],
	"enabled_log_types": log_types,
	"secrets_encrypted": true,
}]}

test_violation_when_no_logging_is_enabled if {
	violations := no_audit.violations with input as _cluster([])
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
	v.severity == "medium"
}

# The other log types do not answer "who did what through the API server".
test_violation_when_other_log_types_are_on_but_audit_is_not if {
	violations := no_audit.violations with input as _cluster(["api", "scheduler"])
	count(violations) == 1
}

test_no_violation_when_audit_logging_is_on if {
	violations := no_audit.violations with input as _cluster(["api", "audit", "authenticator"])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := no_audit.violations with input as {"eks_clusters": []}
	count(violations) == 0
}

test_each_cluster_is_its_own_finding if {
	violations := no_audit.violations with input as {"eks_clusters": [
		{"name": "prod", "region": "eu-west-1", "enabled_log_types": []},
		{"name": "staging", "region": "eu-west-1", "enabled_log_types": ["api"]},
		{"name": "dev", "region": "eu-west-1", "enabled_log_types": ["audit"]},
	]}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
