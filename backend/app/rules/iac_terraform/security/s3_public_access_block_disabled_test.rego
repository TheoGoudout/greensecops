package greensecops.iac_terraform.security.s3_public_access_block_disabled_test

import data.greensecops.iac_terraform.security.s3_public_access_block_disabled as public_access_block
import rego.v1

# A companion resource references its bucket either by resource reference
# (aws_s3_bucket.data.id) or by the literal bucket name, exactly as
# s3_bucket_missing_versioning has to handle.

_all_true := {
	"block_public_acls": true,
	"block_public_policy": true,
	"ignore_public_acls": true,
	"restrict_public_buckets": true,
}

test_violation_when_no_block_exists if {
	violations := public_access_block.violations with input as {"resource": [{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}}]}
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_s3_bucket.data"
}

test_no_violation_when_all_four_settings_are_true if {
	violations := public_access_block.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_public_access_block": {"data": object.union(
			{"bucket": "${aws_s3_bucket.data.id}"},
			_all_true,
		)}},
	]}
	count(violations) == 0
}

test_no_violation_when_referenced_by_the_literal_bucket_name if {
	violations := public_access_block.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_public_access_block": {"whatever": object.union(
			{"bucket": "my-bucket"},
			_all_true,
		)}},
	]}
	count(violations) == 0
}

# All four settings matter — each closes a different route to public — so three
# out of four is still a finding.
test_violation_when_one_setting_is_false if {
	violations := public_access_block.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_public_access_block": {"data": object.union(
			_all_true,
			{"bucket": "${aws_s3_bucket.data.id}", "restrict_public_buckets": false},
		)}},
	]}
	count(violations) == 1
}

test_violation_when_a_setting_is_omitted if {
	violations := public_access_block.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_public_access_block": {"data": {
			"bucket": "${aws_s3_bucket.data.id}",
			"block_public_acls": true,
			"block_public_policy": true,
		}}},
	]}
	count(violations) == 1
}

# A block covering a different bucket must not cover this one.
test_violation_when_the_block_targets_another_bucket if {
	violations := public_access_block.violations with input as {"resource": [
		{"aws_s3_bucket": {"uncovered": {"bucket": "uncovered-bucket"}}},
		{"aws_s3_bucket": {"covered": {"bucket": "covered-bucket"}}},
		{"aws_s3_bucket_public_access_block": {"covered": object.union(
			{"bucket": "${aws_s3_bucket.covered.id}"},
			_all_true,
		)}},
	]}
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_s3_bucket.uncovered"
}

test_no_violation_when_a_second_block_covers_the_bucket_fully if {
	violations := public_access_block.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_public_access_block": {"partial": {
			"bucket": "${aws_s3_bucket.data.id}",
			"block_public_acls": true,
		}}},
		{"aws_s3_bucket_public_access_block": {"full": object.union(
			{"bucket": "${aws_s3_bucket.data.arn}"},
			_all_true,
		)}},
	]}
	count(violations) == 0
}

test_no_violation_when_there_are_no_buckets if {
	violations := public_access_block.violations with input as {"resource": []}
	count(violations) == 0
}
