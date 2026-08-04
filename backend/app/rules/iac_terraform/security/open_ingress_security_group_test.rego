package greensecops.iac_terraform.security.open_ingress_security_group_test

import data.greensecops.iac_terraform.security.open_ingress_security_group as open_ingress
import rego.v1

# A repeated `ingress` block becomes a list; the same block in a .tf.json file
# would be a bare object.

_sg(ingress) := {"resource": [{"aws_security_group": {"web": {
	"name": "web",
	"ingress": ingress,
	"__tf_file": "main.tf",
	"__start_line__": 3,
	"__end_line__": 14,
}}}]}

test_violation_for_ingress_from_anywhere if {
	violations := open_ingress.violations with input as _sg([{
		"from_port": 22,
		"to_port": 22,
		"protocol": "tcp",
		"cidr_blocks": ["0.0.0.0/0"],
	}])
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_security_group.web"
	contains(v.message, "22")
}

test_no_violation_for_a_scoped_cidr if {
	violations := open_ingress.violations with input as _sg([{
		"from_port": 22,
		"to_port": 22,
		"cidr_blocks": ["10.0.0.0/16"],
	}])
	count(violations) == 0
}

test_violation_when_an_open_cidr_sits_alongside_a_scoped_one if {
	violations := open_ingress.violations with input as _sg([{
		"from_port": 443,
		"to_port": 443,
		"cidr_blocks": ["10.0.0.0/16", "0.0.0.0/0"],
	}])
	count(violations) == 1
}

test_no_violation_when_there_are_no_ingress_blocks if {
	violations := open_ingress.violations with input as _sg([])
	count(violations) == 0
}

test_each_open_ingress_block_is_its_own_finding if {
	violations := open_ingress.violations with input as _sg([
		{"from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]},
		{"from_port": 443, "to_port": 443, "cidr_blocks": ["0.0.0.0/0"]},
		{"from_port": 5432, "to_port": 5432, "cidr_blocks": ["10.0.0.0/16"]},
	])
	count(violations) == 2
}
