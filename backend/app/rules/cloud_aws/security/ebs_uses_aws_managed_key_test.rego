package greensecops.cloud_aws.security.ebs_uses_aws_managed_key_test

import data.greensecops.cloud_aws.security.ebs_uses_aws_managed_key as aws_managed
import rego.v1

_customer_key := {"id": "abc-123", "region": "eu-west-1", "rotation_enabled": true}

_input(kms_key_id, keys) := {
	"ebs_volumes": [{
		"id": "vol-0123",
		"region": "eu-west-1",
		"encrypted": true,
		"kms_key_id": kms_key_id,
		"volume_type": "gp3",
		"size_gb": 100,
		"attached": true,
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
	v.resource_id == "vol-0123"
	v.severity == "medium"
}

test_no_violation_when_the_key_is_customer_managed if {
	violations := aws_managed.violations with input as _input(
		"arn:aws:kms:eu-west-1:123456789012:key/abc-123",
		[_customer_key],
	)
	count(violations) == 0
}

# An empty key list is indistinguishable from a missing kms:ListKeys
# permission, and a permission gap must never manufacture a finding.
test_no_violation_when_no_keys_could_be_read if {
	violations := aws_managed.violations with input as _input(
		"arn:aws:kms:eu-west-1:123456789012:key/aws-default-999",
		[],
	)
	count(violations) == 0
}

# An unencrypted volume is ebs_volume_unencrypted's finding, which is larger
# and supersedes this one.
test_no_violation_for_an_unencrypted_volume if {
	violations := aws_managed.violations with input as {
		"ebs_volumes": [{
			"id": "vol-0123",
			"region": "eu-west-1",
			"encrypted": false,
			"kms_key_id": null,
		}],
		"kms_keys": [_customer_key],
	}
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := aws_managed.violations with input as {"ebs_volumes": [], "kms_keys": [_customer_key]}
	count(violations) == 0
}

test_each_volume_is_its_own_finding if {
	violations := aws_managed.violations with input as {
		"ebs_volumes": [
			{"id": "vol-a", "region": "eu-west-1", "encrypted": true, "kms_key_id": "arn:...key/default-1"},
			{"id": "vol-b", "region": "eu-west-1", "encrypted": true, "kms_key_id": "arn:...key/default-2"},
			{"id": "vol-c", "region": "eu-west-1", "encrypted": true, "kms_key_id": "arn:...key/abc-123"},
		],
		"kms_keys": [_customer_key],
	}
	count(violations) == 2
	count({v.resource_id | some v in violations}) == 2
}
