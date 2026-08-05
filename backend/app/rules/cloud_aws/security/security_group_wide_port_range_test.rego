package greensecops.cloud_aws.security.security_group_wide_port_range_test

import data.greensecops.cloud_aws.security.security_group_wide_port_range as wide_range
import rego.v1

# Mirrors services/cloud/aws_collector._collect_security_groups: IPv4 and IPv6
# CIDRs are folded into one `cidr_blocks` list, and an "all protocols" rule is
# reported as ip_protocol "-1" with no meaningful port range.

_sg(ingress_rules) := {"security_groups": [{
	"id": "sg-0123",
	"name": "app",
	"region": "eu-west-1",
	"ingress_rules": ingress_rules,
}]}

_rule(from_port, to_port, cidrs) := {
	"from_port": from_port,
	"to_port": to_port,
	"ip_protocol": "tcp",
	"cidr_blocks": cidrs,
}

test_violation_for_the_full_port_range if {
	violations := wide_range.violations with input as _sg([_rule(0, 65535, ["10.0.0.0/16"])])
	count(violations) == 1
	some v in violations
	v.resource_id == "sg-0123"
	v.region == "eu-west-1"
}

# The finding does not depend on the source: a wide range is over-granting even
# inside a VPC. That is what separates it from open_ingress_security_group.
test_violation_on_a_private_cidr if {
	violations := wide_range.violations with input as _sg([_rule(1024, 65535, ["172.16.0.0/12"])])
	count(violations) == 1
}

test_violation_at_the_range_threshold if {
	violations := wide_range.violations with input as _sg([_rule(8000, 8100, ["10.0.0.0/16"])])
	count(violations) == 1
}

test_no_violation_just_below_the_range_threshold if {
	violations := wide_range.violations with input as _sg([_rule(8000, 8099, ["10.0.0.0/16"])])
	count(violations) == 0
}

test_no_violation_for_a_single_port if {
	violations := wide_range.violations with input as _sg([_rule(5432, 5432, ["10.0.0.0/16"])])
	count(violations) == 0
}

test_violation_for_an_all_protocols_rule if {
	violations := wide_range.violations with input as _sg([{
		"from_port": null,
		"to_port": null,
		"ip_protocol": "-1",
		"cidr_blocks": ["10.0.0.0/16"],
	}])
	count(violations) == 1
	some v in violations
	v.discriminator == "all-protocols"
	contains(v.message, "every protocol")
}

# An all-protocols rule has no port range to measure, so only the second clause
# fires — it must not be double-reported.
test_all_protocols_rule_reports_once if {
	violations := wide_range.violations with input as _sg([{
		"from_port": 0,
		"to_port": 65535,
		"ip_protocol": "-1",
		"cidr_blocks": ["10.0.0.0/16"],
	}])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}

test_no_violation_when_ports_are_absent if {
	violations := wide_range.violations with input as _sg([{"ip_protocol": "tcp", "cidr_blocks": ["10.0.0.0/16"]}])
	count(violations) == 0
}

test_each_wide_rule_is_its_own_finding if {
	violations := wide_range.violations with input as _sg([
		_rule(0, 65535, ["10.0.0.0/16"]),
		_rule(3000, 4000, ["10.0.0.0/16"]),
		_rule(443, 443, ["0.0.0.0/0"]),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
