package greensecops.cloud_aws.security.iam_user_no_mfa_test

import data.greensecops.cloud_aws.security.iam_user_no_mfa
import rego.v1

# Mirrors services/cloud/aws_collector.collect_account_resources: each resource
# type is a list of flat objects. A field the collector could not read is
# omitted rather than defaulted, so "absent" has to be covered alongside
# "false".

_snapshot(resources) := {"iam_users": resources}

_human(extra) := object.union({"name": "alice", "console_access": true}, extra)

test_violation_when_mfa_enabled_is_false if {
	violations := iam_user_no_mfa.violations with input as _snapshot([_human({"mfa_enabled": false})])
	count(violations) == 1
	some v in violations
	v.resource_id == "alice"
	v.resource_type == "aws_iam_user"
}

test_no_violation_when_mfa_enabled_is_true if {
	violations := iam_user_no_mfa.violations with input as _snapshot([_human({"mfa_enabled": true})])
	count(violations) == 0
}

test_violation_when_mfa_enabled_is_absent if {
	violations := iam_user_no_mfa.violations with input as _snapshot([_human({})])
	count(violations) == 1
}

# A service principal authenticates with an access key and has no password, so
# there is nothing for a second factor to protect. Reporting these made every
# CI user in the account a high-severity finding.
test_no_violation_for_a_user_without_console_access if {
	violations := iam_user_no_mfa.violations with input as _snapshot([{"name": "ci-bot", "console_access": false, "mfa_enabled": false}])
	count(violations) == 0
}

# The credential report could not be read for this user, so whether it has a
# password is unknown. Silence beats a high-severity guess.
test_no_violation_when_console_access_is_unknown if {
	violations := iam_user_no_mfa.violations with input as _snapshot([{"name": "legacy", "console_access": null, "mfa_enabled": false}])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := iam_user_no_mfa.violations with input as _snapshot([])
	count(violations) == 0
}

test_each_offending_resource_is_its_own_finding if {
	violations := iam_user_no_mfa.violations with input as _snapshot([
		_human({"name": "alice", "mfa_enabled": false}),
		_human({"name": "bob", "mfa_enabled": false}),
		_human({"name": "carol", "mfa_enabled": true}),
	])
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
