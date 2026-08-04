package greensecops.iac_terraform.reliability.rds_no_deletion_protection_test

import data.greensecops.iac_terraform.reliability.rds_no_deletion_protection
import rego.v1

# Mirrors app.services.terraform.hcl_parser.merge_terraform_configs: `resource`
# is a list of single-key objects nested {type: {name: attrs}}, and source
# metadata rides along under double-underscore keys.

_res(attrs) := {"resource": [{"aws_db_instance": {"main": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 9},
	attrs,
)}}]}

test_violation_protection_absent if {
	violations := rds_no_deletion_protection.violations with input as _res({"identifier": "app-db"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_db_instance.main"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_violation_protection_false if {
	violations := rds_no_deletion_protection.violations with input as _res({"deletion_protection": false})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_db_instance.main"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_no_violation_protection_true if {
	violations := rds_no_deletion_protection.violations with input as _res({"deletion_protection": true})
	count(violations) == 0
}
