package greensecops.container_docker.security.compose_override_exposes_bound_port_test

import data.greensecops.container_docker.security.compose_override_exposes_bound_port as exposes_port
import rego.v1

_files(base_services, override_services) := {"compose_files": [
	{
		"__docker_file": "compose.yml",
		"is_override": false,
		"services": base_services,
	},
	{
		"__docker_file": "compose.override.yml",
		"is_override": true,
		"services": override_services,
	},
]}

_base(ports) := {
	"image": "app:1.0",
	"ports": ports,
	"__start_line__": 2,
	"__end_line__": 6,
}

test_violation_when_the_override_drops_the_host_address if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["127.0.0.1:9990:9990"])},
		{"db": {"ports": ["9990:9990"]}},
	)
	count(violations) == 1
	some v in violations
	v.service_name == "db"
	v.severity == "high"
}

# A bare port publishes on every interface too — the host port is just chosen
# by Docker rather than by the file.
test_violation_for_the_bare_port_form if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["127.0.0.1:9990:9990"])},
		{"db": {"ports": ["9990"]}},
	)
	count(violations) == 1
}

test_no_violation_when_the_override_keeps_a_loopback_binding if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["127.0.0.1:9990:9990"])},
		{"db": {"ports": ["127.0.0.1:19990:9990"]}},
	)
	count(violations) == 0
}

# A different container port is a different decision — the base said nothing
# careful about this one.
test_no_violation_for_an_unrelated_port if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["127.0.0.1:9990:9990"])},
		{"db": {"ports": ["9090:9090"]}},
	)
	count(violations) == 0
}

# compose_port_bound_to_all_interfaces already reports every datastore port
# published on all interfaces, wherever it appears. Firing here too would put
# two findings on one line. What is left to this rule is everything else — an
# admin UI, a debug listener, a metrics endpoint — where nothing else fires.
test_no_violation_for_a_datastore_port_a_dedicated_rule_owns if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["127.0.0.1:5432:5432"])},
		{"db": {"ports": ["5432:5432"]}},
	)
	count(violations) == 0
}

# Nothing was undone if the base published widely to begin with —
# compose_port_bound_to_all_interfaces reports that on its own merits.
test_no_violation_when_the_base_publishes_widely if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["9990:9990"])},
		{"db": {"ports": ["9990:9990"]}},
	)
	count(violations) == 0
}

test_no_violation_when_the_override_adds_no_ports if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["127.0.0.1:9990:9990"])},
		{"db": {"environment": {"DEBUG": "1"}}},
	)
	count(violations) == 0
}

test_no_violation_without_an_override if {
	violations := exposes_port.violations with input as {"compose_files": [{
		"__docker_file": "compose.yml",
		"is_override": false,
		"services": {"db": _base(["127.0.0.1:9990:9990"])},
	}]}
	count(violations) == 0
}

test_each_exposed_port_is_its_own_finding if {
	violations := exposes_port.violations with input as _files(
		{"db": _base(["127.0.0.1:9990:9990", "127.0.0.1:9991:9991"])},
		{"db": {"ports": ["9990:9990", "9991:9991"]}},
	)
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
