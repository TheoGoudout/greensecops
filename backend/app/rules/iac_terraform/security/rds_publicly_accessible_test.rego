package greensecops.iac_terraform.security.rds_publicly_accessible_test

import data.greensecops.iac_terraform.security.rds_publicly_accessible
import rego.v1

# Mirrors app.services.terraform.hcl_parser.merge_terraform_configs: `resource`
# is a list of single-key objects nested {type: {name: attrs}}, and source
# metadata rides along under double-underscore keys.

_res(attrs) := {"resource": [{"aws_db_instance": {"main": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 9},
	attrs,
)}}]}

test_violation_publicly_accessible_true if {
	violations := rds_publicly_accessible.violations with input as _res({"publicly_accessible": true})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_db_instance.main"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_no_violation_publicly_accessible_false if {
	violations := rds_publicly_accessible.violations with input as _res({"publicly_accessible": false})
	count(violations) == 0
}

test_no_violation_attribute_absent if {
	violations := rds_publicly_accessible.violations with input as _res({"identifier": "app-db"})
	count(violations) == 0
}
