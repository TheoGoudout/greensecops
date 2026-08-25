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
		"from_port": 3389,
		"to_port": 3389,
		"cidr_blocks": ["10.0.0.0/16", "0.0.0.0/0"],
	}])
	count(violations) == 1
}

# Publishing HTTPS is what a public service is; this was reported at critical.
test_no_violation_for_https_open_to_the_world if {
	violations := open_ingress.violations with input as _sg([{
		"from_port": 443,
		"to_port": 443,
		"cidr_blocks": ["0.0.0.0/0"],
	}])
	count(violations) == 0
}

test_violation_for_a_range_containing_https if {
	violations := open_ingress.violations with input as _sg([{
		"from_port": 0,
		"to_port": 65535,
		"cidr_blocks": ["0.0.0.0/0"],
	}])
	count(violations) == 1
}

# The rule read only `cidr_blocks`, so an IPv6-only open rule was invisible.
test_violation_for_an_open_ipv6_cidr if {
	violations := open_ingress.violations with input as _sg([{
		"from_port": 22,
		"to_port": 22,
		"ipv6_cidr_blocks": ["::/0"],
	}])
	count(violations) == 1
}

# The standalone rule resource — not read at all before.
test_violation_for_aws_security_group_rule if {
	violations := open_ingress.violations with input as {"resource": [{"aws_security_group_rule": {"ssh": {
		"type": "ingress",
		"from_port": 22,
		"to_port": 22,
		"cidr_blocks": ["0.0.0.0/0"],
		"__tf_file": "main.tf",
	}}}]}
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_security_group_rule.ssh"
}

test_no_violation_for_an_egress_rule_resource if {
	violations := open_ingress.violations with input as {"resource": [{"aws_security_group_rule": {"out": {
		"type": "egress",
		"from_port": 0,
		"to_port": 0,
		"cidr_blocks": ["0.0.0.0/0"],
		"__tf_file": "main.tf",
	}}}]}
	count(violations) == 0
}

# The form the AWS provider has recommended since v5.
test_violation_for_aws_vpc_security_group_ingress_rule if {
	violations := open_ingress.violations with input as {"resource": [{"aws_vpc_security_group_ingress_rule": {"ssh": {
		"cidr_ipv4": "0.0.0.0/0",
		"from_port": 22,
		"to_port": 22,
		"ip_protocol": "tcp",
		"__tf_file": "main.tf",
	}}}]}
	count(violations) == 1
	some v in violations
	v.resource_address == "aws_vpc_security_group_ingress_rule.ssh"
}

test_no_violation_for_a_scoped_v5_rule if {
	violations := open_ingress.violations with input as {"resource": [{"aws_vpc_security_group_ingress_rule": {"ssh": {
		"cidr_ipv4": "10.0.0.0/16",
		"from_port": 22,
		"to_port": 22,
		"__tf_file": "main.tf",
	}}}]}
	count(violations) == 0
}

test_no_violation_when_there_are_no_ingress_blocks if {
	violations := open_ingress.violations with input as _sg([])
	count(violations) == 0
}

test_each_open_ingress_block_is_its_own_finding if {
	violations := open_ingress.violations with input as _sg([
		{"from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]},
		{"from_port": 3389, "to_port": 3389, "cidr_blocks": ["0.0.0.0/0"]},
		{"from_port": 5432, "to_port": 5432, "cidr_blocks": ["10.0.0.0/16"]},
	])
	count(violations) == 2
}

# Several open blocks on one group used to collapse to a single issue row.
test_each_open_block_has_a_distinct_dedup_key if {
	violations := open_ingress.violations with input as _sg([
		{"from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]},
		{"from_port": 3389, "to_port": 3389, "cidr_blocks": ["0.0.0.0/0"]},
		{"from_port": 5432, "to_port": 5432, "cidr_blocks": ["0.0.0.0/0"]},
	])
	count(violations) == 3
	count({v.discriminator | some v in violations}) == 3
}

test_the_json_object_form_of_a_single_block if {
	violations := open_ingress.violations with input as _sg({
		"from_port": 22,
		"to_port": 22,
		"cidr_blocks": ["0.0.0.0/0"],
	})
	count(violations) == 1
}
