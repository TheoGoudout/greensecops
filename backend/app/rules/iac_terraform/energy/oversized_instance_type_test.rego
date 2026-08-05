package greensecops.iac_terraform.energy.oversized_instance_type_test

import data.greensecops.iac_terraform.energy.oversized_instance_type as oversized
import rego.v1

_res(res_type, instance_type) := {"resource": [{res_type: {"worker": {
	"instance_type": instance_type,
	"__tf_file": "main.tf",
	"__start_line__": 3,
	"__end_line__": 8,
}}}]}

test_violation_for_16xlarge if {
	violations := oversized.violations with input as _res("aws_instance", "m5.16xlarge")
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_instance.worker"
	contains(v.message, "m5.16xlarge")
}

test_violation_for_8xlarge if {
	violations := oversized.violations with input as _res("aws_instance", "c6i.8xlarge")
	count(violations) == 1
}

test_violation_for_a_metal_instance if {
	violations := oversized.violations with input as _res("aws_instance", "m5.metal")
	count(violations) == 1
}

test_violation_on_a_launch_template if {
	violations := oversized.violations with input as _res("aws_launch_template", "r6i.12xlarge")
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_launch_template.worker"
}

# The threshold starts at 8xlarge — smaller sizes are ordinary decisions.
test_no_violation_for_4xlarge if {
	violations := oversized.violations with input as _res("aws_instance", "m5.4xlarge")
	count(violations) == 0
}

test_no_violation_for_2xlarge if {
	violations := oversized.violations with input as _res("aws_instance", "m5.2xlarge")
	count(violations) == 0
}

test_no_violation_for_a_plain_xlarge if {
	violations := oversized.violations with input as _res("aws_instance", "t3.xlarge")
	count(violations) == 0
}

test_no_violation_for_a_small_instance if {
	violations := oversized.violations with input as _res("aws_instance", "t3.micro")
	count(violations) == 0
}

# An unresolved variable reference is not a size this rule can judge.
test_no_violation_for_an_interpolated_instance_type if {
	violations := oversized.violations with input as _res("aws_instance", "${var.instance_type}")
	count(violations) == 0
}

test_no_violation_when_instance_type_is_absent if {
	violations := oversized.violations with input as {"resource": [{"aws_instance": {"worker": {"ami": "ami-1"}}}]}
	count(violations) == 0
}
