package greensecops.container_docker.security.compose_override_disables_read_only_test

import data.greensecops.container_docker.security.compose_override_disables_read_only as disables_read_only
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

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_the_override_turns_read_only_off if {
	violations := disables_read_only.violations with input as _files(
		{"api": _service({"read_only": true})},
		{"api": {"read_only": false}},
	)
	count(violations) == 1
	some v in violations
	v.service_name == "api"
	v.file_path == "compose.override.yml"
}

test_no_violation_when_the_override_leaves_it_alone if {
	violations := disables_read_only.violations with input as _files(
		{"api": _service({"read_only": true})},
		{"api": {"tmpfs": ["/tmp"]}},
	)
	count(violations) == 0
}

test_no_violation_when_the_override_keeps_it_on if {
	violations := disables_read_only.violations with input as _files(
		{"api": _service({"read_only": true})},
		{"api": {"read_only": true}},
	)
	count(violations) == 0
}

# Nothing was weakened if the base never set it.
test_no_violation_when_the_base_is_not_read_only if {
	violations := disables_read_only.violations with input as _files(
		{"api": _service({})},
		{"api": {"read_only": false}},
	)
	count(violations) == 0
}

test_no_violation_without_an_override if {
	violations := disables_read_only.violations with input as {"compose_files": [{
		"__docker_file": "compose.yml",
		"is_override": false,
		"services": {"api": _service({"read_only": true})},
	}]}
	count(violations) == 0
}

test_each_weakened_service_is_its_own_finding if {
	violations := disables_read_only.violations with input as _files(
		{
			"api": _service({"read_only": true}),
			"worker": _service({"read_only": true}),
		},
		{
			"api": {"read_only": false},
			"worker": {"read_only": false},
		},
	)
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
