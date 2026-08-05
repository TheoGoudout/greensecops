package greensecops.cloud_aws.security.security_group_unrestricted_egress_test

import data.greensecops.cloud_aws.security.security_group_unrestricted_egress as open_egress
import rego.v1

_sg(egress_rules) := {"security_groups": [{
	"id": "sg-0123",
	"name": "web",
	"region": "eu-west-1",
	"ingress_rules": [],
	"egress_rules": egress_rules,
}]}

_rule(protocol, cidrs) := {
	"from_port": null,
	"to_port": null,
	"ip_protocol": protocol,
	"cidr_blocks": cidrs,
}

test_violation_for_the_default_allow_all_egress if {
	violations := open_egress.violations with input as _sg([_rule("-1", ["0.0.0.0/0"])])
	count(violations) == 1
	some v in violations
	v.resource_id == "sg-0123"
	v.severity == "medium"
}

test_violation_for_the_ipv6_form if {
	violations := open_egress.violations with input as _sg([_rule("-1", ["::/0"])])
	count(violations) == 1
}

# Egress restricted to a protocol is a decision somebody made, which is the
# behaviour this rule is asking for.
test_no_violation_when_egress_names_a_protocol if {
	violations := open_egress.violations with input as _sg([_rule("tcp", ["0.0.0.0/0"])])
	count(violations) == 0
}

test_no_violation_when_egress_is_scoped_to_a_cidr if {
	violations := open_egress.violations with input as _sg([_rule("-1", ["10.0.0.0/16"])])
	count(violations) == 0
}

test_no_violation_when_a_group_has_no_egress_rules if {
	violations := open_egress.violations with input as _sg([])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := open_egress.violations with input as {"security_groups": []}
	count(violations) == 0
}

# Ingress is a separate rule's concern; an open ingress rule must not make this
# one fire.
test_no_violation_from_an_open_ingress_rule if {
	violations := open_egress.violations with input as {"security_groups": [{
		"id": "sg-0123",
		"name": "web",
		"region": "eu-west-1",
		"ingress_rules": [_rule("-1", ["0.0.0.0/0"])],
		"egress_rules": [],
	}]}
	count(violations) == 0
}

test_both_address_families_are_separate_findings if {
	violations := open_egress.violations with input as _sg([_rule("-1", ["0.0.0.0/0", "::/0"])])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
