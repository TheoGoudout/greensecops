package greensecops.iac_terraform.energy.gp2_volume_type_test

import data.greensecops.iac_terraform.energy.gp2_volume_type
import rego.v1

_volume(attrs) := {"resource": [{"aws_ebs_volume": {"data": object.union(
	{"__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 8},
	attrs,
)}}]}

_instance(attrs) := {"resource": [{"aws_instance": {"web": object.union(
	{"ami": "ami-1", "__tf_file": "main.tf", "__start_line__": 3, "__end_line__": 12},
	attrs,
)}}]}

test_violation_for_a_gp2_volume if {
	violations := gp2_volume_type.violations with input as _volume({"type": "gp2", "size": 500})
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_ebs_volume.data"
}

test_no_violation_for_a_gp3_volume if {
	violations := gp2_volume_type.violations with input as _volume({"type": "gp3", "size": 100})
	count(violations) == 0
}

test_no_violation_for_io2 if {
	violations := gp2_volume_type.violations with input as _volume({"type": "io2", "iops": 8000})
	count(violations) == 0
}

test_no_violation_when_type_is_absent if {
	violations := gp2_volume_type.violations with input as _volume({"size": 100})
	count(violations) == 0
}

# Most gp2 volumes are declared as an instance's block device rather than as a
# standalone aws_ebs_volume.
test_violation_for_a_gp2_root_block_device if {
	violations := gp2_volume_type.violations with input as _instance({"root_block_device": [{"volume_type": "gp2"}]})
	count(violations) == 1
	some v in violations
	v.discriminator == "root_block_device"
}

test_violation_for_a_gp2_ebs_block_device if {
	violations := gp2_volume_type.violations with input as _instance({"ebs_block_device": [{"volume_type": "gp2"}]})
	count(violations) == 1
	some v in violations
	v.discriminator == "ebs_block_device"
}

test_no_violation_for_a_gp3_root_block_device if {
	violations := gp2_volume_type.violations with input as _instance({"root_block_device": [{"volume_type": "gp3"}]})
	count(violations) == 0
}

# .tf.json carries a nested block as a bare object rather than a list.
test_violation_for_the_json_style_object_form if {
	violations := gp2_volume_type.violations with input as _instance({"root_block_device": {"volume_type": "gp2"}})
	count(violations) == 1
}

test_both_device_kinds_on_one_instance_are_separate_findings if {
	violations := gp2_volume_type.violations with input as _instance({
		"root_block_device": [{"volume_type": "gp2"}],
		"ebs_block_device": [{"volume_type": "gp2"}],
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
