package greensecops.iac_terraform.security.unencrypted_ebs_volume_test

import data.greensecops.iac_terraform.security.unencrypted_ebs_volume
import rego.v1

_volume(attrs) := {"resource": [{"aws_ebs_volume": {"data": object.union(
	{"availability_zone": "eu-west-1a", "size": 100, "__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 8},
	attrs,
)}}]}

test_violation_when_encryption_is_absent if {
	violations := unencrypted_ebs_volume.violations with input as _volume({})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_ebs_volume.data"
}

test_violation_when_encryption_is_false if {
	violations := unencrypted_ebs_volume.violations with input as _volume({"encrypted": false})
	count(violations) == 1
}

test_no_violation_when_encrypted if {
	violations := unencrypted_ebs_volume.violations with input as _volume({"encrypted": true})
	count(violations) == 0
}

test_each_unencrypted_volume_is_its_own_finding if {
	violations := unencrypted_ebs_volume.violations with input as {"resource": [
		{"aws_ebs_volume": {"a": {"size": 10}}},
		{"aws_ebs_volume": {"b": {"size": 10, "encrypted": false}}},
		{"aws_ebs_volume": {"c": {"size": 10, "encrypted": true}}},
	]}
	count(violations) == 2
}
