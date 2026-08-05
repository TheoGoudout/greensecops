package greensecops.iac_terraform.security.ecr_mutable_image_tags_test

import data.greensecops.iac_terraform.security.ecr_mutable_image_tags
import rego.v1

# Mirrors app.services.terraform.hcl_parser.merge_terraform_configs: `resource`
# is a list of single-key objects nested {type: {name: attrs}}, and source
# metadata rides along under double-underscore keys.

_res(attrs) := {"resource": [{"aws_ecr_repository": {"app": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 9},
	attrs,
)}}]}

test_violation_mutability_is_mutable if {
	violations := ecr_mutable_image_tags.violations with input as _res({"image_tag_mutability": "MUTABLE"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_ecr_repository.app"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_violation_mutability_absent_defaults_to_mutable if {
	violations := ecr_mutable_image_tags.violations with input as _res({"name": "app"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_ecr_repository.app"
	v.file_path == "main.tf"
	v.line_start == 3
}

test_no_violation_mutability_is_immutable if {
	violations := ecr_mutable_image_tags.violations with input as _res({"image_tag_mutability": "IMMUTABLE"})
	count(violations) == 0
}
