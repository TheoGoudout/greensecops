package greensecops.iac_terraform.reliability.s3_bucket_missing_versioning_test

import data.greensecops.iac_terraform.reliability.s3_bucket_missing_versioning
import rego.v1

# Mirrors what app.services.terraform.hcl_parser.merge_terraform_configs
# produces: `resource` is a list of single-key objects, and a nested HCL block
# (`versioning`, `versioning_configuration`) becomes a single-element list.

test_violation_when_no_versioning_at_all if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}}]}
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_s3_bucket.data"
}

test_no_violation_with_inline_versioning_block if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [{"aws_s3_bucket": {"data": {
		"bucket": "my-bucket",
		"versioning": [{"enabled": true}],
	}}}]}
	count(violations) == 0
}

test_no_violation_with_companion_versioning_resource_by_id if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_versioning": {"data": {
			"bucket": "${aws_s3_bucket.data.id}",
			"versioning_configuration": [{"status": "Enabled"}],
		}}},
	]}
	count(violations) == 0
}

test_no_violation_with_companion_versioning_resource_by_bucket_attribute if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_versioning": {"whatever_name": {
			"bucket": "${aws_s3_bucket.data.bucket}",
			"versioning_configuration": [{"status": "Enabled"}],
		}}},
	]}
	count(violations) == 0
}

test_no_violation_when_both_resources_name_the_bucket_literally if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_versioning": {"data": {
			"bucket": "my-bucket",
			"versioning_configuration": [{"status": "Enabled"}],
		}}},
	]}
	count(violations) == 0
}

# .tf.json carries the block as a bare object rather than a single-element list.
test_no_violation_with_json_style_object_configuration if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_versioning": {"data": {
			"bucket": "${aws_s3_bucket.data.id}",
			"versioning_configuration": {"status": "Enabled"},
		}}},
	]}
	count(violations) == 0
}

test_violation_when_companion_resource_suspends_versioning if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [
		{"aws_s3_bucket": {"data": {"bucket": "my-bucket"}}},
		{"aws_s3_bucket_versioning": {"data": {
			"bucket": "${aws_s3_bucket.data.id}",
			"versioning_configuration": [{"status": "Suspended"}],
		}}},
	]}
	count(violations) == 1
}

# A companion resource for a *different* bucket must not cover this one.
test_violation_when_companion_resource_targets_another_bucket if {
	violations := s3_bucket_missing_versioning.violations with input as {"resource": [
		{"aws_s3_bucket": {"uncovered": {"bucket": "uncovered-bucket"}}},
		{"aws_s3_bucket": {"covered": {"bucket": "covered-bucket"}}},
		{"aws_s3_bucket_versioning": {"covered": {
			"bucket": "${aws_s3_bucket.covered.id}",
			"versioning_configuration": [{"status": "Enabled"}],
		}}},
	]}
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_s3_bucket.uncovered"
}
