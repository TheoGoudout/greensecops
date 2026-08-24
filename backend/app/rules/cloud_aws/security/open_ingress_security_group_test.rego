package greensecops.cloud_aws.security.open_ingress_security_group_test

import data.greensecops.cloud_aws.security.open_ingress_security_group as open_ingress
import rego.v1

# The collector folds a rule's IPv4 and IPv6 CIDRs into one `cidr_blocks` list,
# so both families arrive through the same field.

_sg(ingress_rules) := {"security_groups": [{
	"id": "sg-0123",
	"name": "web",
	"region": "eu-west-1",
	"ingress_rules": ingress_rules,
}]}

_rule(from_port, to_port, cidrs) := {
	"from_port": from_port,
	"to_port": to_port,
	"ip_protocol": "tcp",
	"cidr_blocks": cidrs,
}

test_violation_for_ipv4_open_to_the_world if {
	violations := open_ingress.violations with input as _sg([_rule(22, 22, ["0.0.0.0/0"])])
	count(violations) == 1
	some v in violations
	v.resource_id == "sg-0123"
	v.region == "eu-west-1"
	v.severity == "critical"
}

test_violation_for_ipv6_open_to_the_world if {
	violations := open_ingress.violations with input as _sg([_rule(3389, 3389, ["::/0"])])
	count(violations) == 1
}

# A public service publishes 80 and 443 — that is what makes it public.
test_no_violation_for_https_open_to_the_world if {
	violations := open_ingress.violations with input as _sg([_rule(443, 443, ["0.0.0.0/0"])])
	count(violations) == 0
}

test_no_violation_for_http_open_to_the_world if {
	violations := open_ingress.violations with input as _sg([_rule(80, 80, ["0.0.0.0/0"])])
	count(violations) == 0
}

# A range that merely contains 443 is not "port 443 is published".
test_violation_for_a_range_containing_https if {
	violations := open_ingress.violations with input as _sg([_rule(0, 65535, ["0.0.0.0/0"])])
	count(violations) == 1
	some v in violations
	contains(v.message, "0-65535")
}

test_violation_for_all_protocols_with_no_port_range if {
	violations := open_ingress.violations with input as {"security_groups": [{
		"id": "sg-0123",
		"name": "web",
		"region": "eu-west-1",
		"ingress_rules": [{"ip_protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}],
	}]}
	count(violations) == 1
	some v in violations
	contains(v.message, "every port")
}

test_violation_when_an_open_cidr_sits_alongside_a_scoped_one if {
	violations := open_ingress.violations with input as _sg([_rule(22, 22, ["10.0.0.0/16", "0.0.0.0/0"])])
	count(violations) == 1
}

test_no_violation_for_a_scoped_cidr if {
	violations := open_ingress.violations with input as _sg([_rule(22, 22, ["10.0.0.0/16"])])
	count(violations) == 0
}

# A /1 is enormous but is not the literal any-address route this rule reports.
test_no_violation_for_a_wide_but_not_open_cidr if {
	violations := open_ingress.violations with input as _sg([_rule(22, 22, ["128.0.0.0/1"])])
	count(violations) == 0
}

test_no_violation_when_a_group_has_no_ingress_rules if {
	violations := open_ingress.violations with input as _sg([])
	count(violations) == 0
}

test_no_violation_for_an_empty_account if {
	violations := open_ingress.violations with input as {"security_groups": []}
	count(violations) == 0
}

test_message_names_the_port if {
	violations := open_ingress.violations with input as _sg([_rule(3389, 3389, ["0.0.0.0/0"])])
	some v in violations
	contains(v.message, "3389")
}

test_each_open_rule_is_its_own_finding if {
	violations := open_ingress.violations with input as _sg([
		_rule(22, 22, ["0.0.0.0/0"]),
		_rule(3389, 3389, ["0.0.0.0/0"]),
		_rule(5432, 5432, ["10.0.0.0/16"]),
	])
	count(violations) == 2
}

# Three open ports on one group used to collapse to a single issue row, because
# the dedup key is (resource_id, discriminator) and there was no discriminator.
test_each_open_rule_has_a_distinct_dedup_key if {
	violations := open_ingress.violations with input as _sg([
		_rule(22, 22, ["0.0.0.0/0"]),
		_rule(3389, 3389, ["0.0.0.0/0"]),
		_rule(5432, 5432, ["0.0.0.0/0"]),
	])
	count(violations) == 3
	count({v.discriminator | some v in violations}) == 3
}

test_both_families_on_one_rule_are_distinct_findings if {
	violations := open_ingress.violations with input as _sg([_rule(22, 22, ["0.0.0.0/0", "::/0"])])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
