package greensecops.cloud_aws.security.s3_public_access_block_disabled_test

import data.greensecops.cloud_aws.security.s3_public_access_block_disabled as public_access_block
import rego.v1

# The collector flattens GetPublicAccessBlock into four booleans, defaulting
# each to False when the call returns nothing — which is the same answer AWS
# gives for a bucket with no block configured at all.

_all_true := {
	"block_public_acls": true,
	"block_public_policy": true,
	"ignore_public_acls": true,
	"restrict_public_buckets": true,
}

_bucket(name, settings) := {"s3_buckets": [object.union(
	object.union({"name": name, "encrypted": true, "versioning_enabled": true}, _all_true),
	settings,
)]}

test_no_violation_when_all_four_are_enabled if {
	violations := public_access_block.violations with input as _bucket("assets", {})
	count(violations) == 0
}

# Each setting closes a different route to public, so any one of them off is
# the finding — this is the case a rule written as "block_public_acls only"
# would miss.
test_violation_when_block_public_acls_is_off if {
	violations := public_access_block.violations with input as _bucket("assets", {"block_public_acls": false})
	count(violations) == 1
	some v in violations
	v.resource_id == "assets"
	v.resource_type == "aws_s3_bucket"
}

test_violation_when_block_public_policy_is_off if {
	violations := public_access_block.violations with input as _bucket("assets", {"block_public_policy": false})
	count(violations) == 1
}

test_violation_when_ignore_public_acls_is_off if {
	violations := public_access_block.violations with input as _bucket("assets", {"ignore_public_acls": false})
	count(violations) == 1
}

test_violation_when_restrict_public_buckets_is_off if {
	violations := public_access_block.violations with input as _bucket("assets", {"restrict_public_buckets": false})
	count(violations) == 1
}

# A bucket with no block at all reaches the rule as all four false.
test_violation_when_no_block_is_configured if {
	violations := public_access_block.violations with input as {"s3_buckets": [{
		"name": "assets",
		"encrypted": true,
		"versioning_enabled": true,
		"block_public_acls": false,
		"block_public_policy": false,
		"ignore_public_acls": false,
		"restrict_public_buckets": false,
	}]}
	count(violations) == 1
}

test_no_violation_for_an_empty_account if {
	violations := public_access_block.violations with input as {"s3_buckets": []}
	count(violations) == 0
}

test_each_exposed_bucket_is_its_own_finding if {
	violations := public_access_block.violations with input as {"s3_buckets": [
		object.union({"name": "a"}, object.union(_all_true, {"block_public_acls": false})),
		object.union({"name": "b"}, object.union(_all_true, {"restrict_public_buckets": false})),
		object.union({"name": "c"}, _all_true),
	]}
	count(violations) == 2
	{v.resource_id | some v in violations} == {"a", "b"}
}
