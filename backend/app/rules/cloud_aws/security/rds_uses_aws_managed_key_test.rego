package greensecops.cloud_aws.security.rds_uses_aws_managed_key_test

import data.greensecops.cloud_aws.security.rds_uses_aws_managed_key as aws_managed
import rego.v1

_customer_key := {"id": "abc-123", "region": "eu-west-1", "rotation_enabled": true}

_input(kms_key_id, keys) := {
	"rds_instances": [{
		"id": "prod",
		"region": "eu-west-1",
		"engine": "postgres",
		"storage_encrypted": true,
		"kms_key_id": kms_key_id,
		"publicly_accessible": false,
	}],
	"kms_keys": keys,
}

test_violation_when_the_key_is_not_customer_managed if {
	violations := aws_managed.violations with input as _input(
		"arn:aws:kms:eu-west-1:123456789012:key/aws-default-999",
		[_customer_key],
	)
	count(violations) == 1
	some v in violations
	v.resource_id == "prod"
}

test_no_violation_when_the_key_is_customer_managed if {
	violations := aws_managed.violations with input as _input(
		"arn:aws:kms:eu-west-1:123456789012:key/abc-123",
		[_customer_key],
	)
	count(violations) == 0
}

test_no_violation_when_no_keys_could_be_read if {
	violations := aws_managed.violations with input as _input(
		"arn:aws:kms:eu-west-1:123456789012:key/aws-default-999",
		[],
	)
	count(violations) == 0
}

# rds_not_encrypted reports the larger problem and supersedes this one.
test_no_violation_for_an_unencrypted_instance if {
	violations := aws_managed.violations with input as {
		"rds_instances": [{
			"id": "prod",
			"region": "eu-west-1",
			"storage_encrypted": false,
			"kms_key_id": null,
		}],
		"kms_keys": [_customer_key],
	}
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := aws_managed.violations with input as {"rds_instances": [], "kms_keys": [_customer_key]}
	count(violations) == 0
}
