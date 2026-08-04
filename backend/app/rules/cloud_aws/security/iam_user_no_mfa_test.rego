package greensecops.cloud_aws.security.iam_user_no_mfa_test

import data.greensecops.cloud_aws.security.iam_user_no_mfa
import rego.v1

# Mirrors services/cloud/aws_collector.collect_account_resources: each resource
# type is a list of flat objects. A field the collector could not read is
# omitted rather than defaulted, so "absent" has to be covered alongside
# "false".

_snapshot(resources) := {"iam_users": resources}

test_violation_when_mfa_enabled_is_false if {
	violations := iam_user_no_mfa.violations with input as _snapshot([{"name": "deploy", "mfa_enabled": false}])
	count(violations) == 1
	some v in violations
	v.resource_id == "deploy"
	v.resource_type == "aws_iam_user"
}

test_no_violation_when_mfa_enabled_is_true if {
	violations := iam_user_no_mfa.violations with input as _snapshot([{"name": "admin", "mfa_enabled": true}])
	count(violations) == 0
}

test_violation_when_mfa_enabled_is_absent if {
	violations := iam_user_no_mfa.violations with input as _snapshot([{"name": "deploy"}])
	count(violations) == 1
}

test_no_violation_for_an_empty_account if {
	violations := iam_user_no_mfa.violations with input as _snapshot([])
	count(violations) == 0
}

test_each_offending_resource_is_its_own_finding if {
	violations := iam_user_no_mfa.violations with input as _snapshot([{"name": "deploy", "mfa_enabled": false}, {"name": "ops", "mfa_enabled": false}, {"name": "admin", "mfa_enabled": true}])
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
