package greensecops.iac_terraform.maintainability.resource_missing_tags_test

import data.greensecops.iac_terraform.maintainability.resource_missing_tags as missing_tags
import rego.v1

# Scoped to a list of taggable types, so an untaggable resource is not
# reported for lacking something it cannot have.

_res(res_type, attrs) := {"resource": [{res_type: {"main": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 8},
	attrs,
)}}]}

test_violation_when_a_taggable_resource_has_no_tags if {
	violations := missing_tags.violations with input as _res("aws_s3_bucket", {"bucket": "my-bucket"})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_s3_bucket.main"
}

test_no_violation_when_tags_are_present if {
	violations := missing_tags.violations with input as _res("aws_s3_bucket", {
		"bucket": "my-bucket",
		"tags": {"Team": "platform"},
	})
	count(violations) == 0
}

# An interpolated tags value (tags = local.common_tags) is still tags.
test_no_violation_for_interpolated_tags if {
	violations := missing_tags.violations with input as _res("aws_instance", {"tags": "${local.common_tags}"})
	count(violations) == 0
}

# A resource type that takes no tags must not be reported.
test_no_violation_for_an_untaggable_resource_type if {
	violations := missing_tags.violations with input as _res("aws_s3_bucket_versioning", {"bucket": "my-bucket"})
	count(violations) == 0
}

test_each_untagged_resource_is_its_own_finding if {
	violations := missing_tags.violations with input as {"resource": [
		{"aws_s3_bucket": {"a": {"bucket": "a"}}},
		{"aws_instance": {"b": {"ami": "ami-1"}}},
		{"aws_vpc": {"c": {"cidr_block": "10.0.0.0/16", "tags": {"Team": "platform"}}}},
	]}
	count(violations) == 2
	{v.resource_address | some v in violations} == {"aws_s3_bucket.a", "aws_instance.b"}
}
