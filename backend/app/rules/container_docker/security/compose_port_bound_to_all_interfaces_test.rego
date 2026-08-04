package greensecops.container_docker.security.compose_port_bound_to_all_interfaces_test

import data.greensecops.container_docker.security.compose_port_bound_to_all_interfaces as bound_to_all
import rego.v1

# Compose accepts several spellings for a published port and the parser passes
# them through untouched: an unquoted `- 5432` arrives as an integer, the short
# syntax as a string with two or three colon-separated parts, and the long
# syntax as a mapping.

_compose(services) := {"compose_files": [{
	"__docker_file": "compose.yml",
	"is_override": false,
	"services": services,
}]}

_service(ports) := {
	"image": "postgres:18",
	"ports": ports,
	"__start_line__": 2,
	"__end_line__": 8,
}

test_violation_for_short_syntax_without_a_host_ip if {
	violations := bound_to_all.violations with input as _compose({"db": _service(["5432:5432"])})
	count(violations) == 1
	some v in violations
	v.service_name == "db"
	contains(v.message, "PostgreSQL")
}

test_no_violation_when_bound_to_loopback if {
	violations := bound_to_all.violations with input as _compose({"db": _service(["127.0.0.1:5432:5432"])})
	count(violations) == 0
}

test_violation_when_explicitly_bound_to_all_interfaces if {
	violations := bound_to_all.violations with input as _compose({"db": _service(["0.0.0.0:5432:5432"])})
	count(violations) == 1
}

test_violation_for_long_syntax_without_a_host_ip if {
	violations := bound_to_all.violations with input as _compose({"db": _service([{
		"target": 5432,
		"published": 5432,
		"protocol": "tcp",
	}])})
	count(violations) == 1
}

test_no_violation_for_long_syntax_bound_to_loopback if {
	violations := bound_to_all.violations with input as _compose({"db": _service([{
		"target": 5432,
		"published": 5432,
		"host_ip": "127.0.0.1",
	}])})
	count(violations) == 0
}

# Compose 2.x renders `published` as a string in the long syntax.
test_violation_for_long_syntax_with_a_string_port if {
	violations := bound_to_all.violations with input as _compose({"cache": _service([{
		"target": 6379,
		"published": "6379",
	}])})
	count(violations) == 1
	some v in violations
	contains(v.message, "Redis")
}

# An unquoted port in YAML is an integer, not a string.
test_violation_for_a_bare_numeric_port if {
	violations := bound_to_all.violations with input as _compose({"db": _service([5432])})
	count(violations) == 1
}

# A web port published on purpose is not this finding.
test_no_violation_for_an_application_port if {
	violations := bound_to_all.violations with input as _compose({"web": _service(["8080:8080"])})
	count(violations) == 0
}

# Services on the same Compose network reach each other without publishing.
test_no_violation_when_no_ports_are_published if {
	violations := bound_to_all.violations with input as _compose({"db": {
		"image": "postgres:18",
		"__start_line__": 2,
		"__end_line__": 4,
	}})
	count(violations) == 0
}

test_no_violation_for_a_null_service if {
	violations := bound_to_all.violations with input as _compose({"db": null})
	count(violations) == 0
}

# The host port is what is exposed; a container port that happens to be 5432
# mapped to a different host port is matched on the host side.
test_matches_on_the_host_port_not_the_container_port if {
	violations := bound_to_all.violations with input as _compose({"db": _service(["15432:5432"])})
	count(violations) == 0
}

test_each_exposed_datastore_port_is_its_own_finding if {
	violations := bound_to_all.violations with input as _compose({
		"db": _service(["5432:5432"]),
		"cache": _service(["6379:6379"]),
		"web": _service(["8080:8080"]),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
