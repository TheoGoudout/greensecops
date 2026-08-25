package greensecops.iac_terraform.security.rds_not_encrypted_test

import data.greensecops.iac_terraform.security.rds_not_encrypted
import rego.v1

_db(attrs) := {"resource": [{"aws_db_instance": {"main": object.union(
	{"identifier": "app-db", "__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 12},
	attrs,
)}}]}

test_violation_when_encryption_is_absent if {
	violations := rds_not_encrypted.violations with input as _db({})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_db_instance.main"
}

test_violation_when_encryption_is_false if {
	violations := rds_not_encrypted.violations with input as _db({"storage_encrypted": false})
	count(violations) == 1
}

test_no_violation_when_encrypted if {
	violations := rds_not_encrypted.violations with input as _db({"storage_encrypted": true})
	count(violations) == 0
}

test_each_unencrypted_instance_is_its_own_finding if {
	violations := rds_not_encrypted.violations with input as {"resource": [
		{"aws_db_instance": {"a": {"identifier": "a"}}},
		{"aws_db_instance": {"b": {"identifier": "b", "storage_encrypted": false}}},
		{"aws_db_instance": {"c": {"identifier": "c", "storage_encrypted": true}}},
	]}
	count(violations) == 2
}

# hcl2 does not evaluate expressions, so a module taking the setting as an
# input arrives as interpolation text. Reporting that as unencrypted reported
# the module rather than the configuration.
test_no_violation_when_encryption_is_a_variable if {
	violations := rds_not_encrypted.violations with input as _db({"storage_encrypted": "${var.encrypt}"})
	count(violations) == 0
}

test_no_violation_for_the_json_string_form if {
	violations := rds_not_encrypted.violations with input as _db({"storage_encrypted": "true"})
	count(violations) == 0
}

test_violation_for_the_json_string_false if {
	violations := rds_not_encrypted.violations with input as _db({"storage_encrypted": "false"})
	count(violations) == 1
}
