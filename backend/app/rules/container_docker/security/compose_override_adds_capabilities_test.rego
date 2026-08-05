package greensecops.container_docker.security.compose_override_adds_capabilities_test

import data.greensecops.container_docker.security.compose_override_adds_capabilities as adds_caps
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

_hardened := {
	"image": "app:1.0",
	"cap_drop": ["ALL"],
	"__start_line__": 2,
	"__end_line__": 6,
}

test_violation_when_the_override_adds_net_admin if {
	violations := adds_caps.violations with input as _files(
		{"api": _hardened},
		{"api": {"cap_add": ["NET_ADMIN"]}},
	)
	count(violations) == 1
	some v in violations
	v.service_name == "api"
	v.severity == "high"
}

test_matching_is_case_insensitive if {
	violations := adds_caps.violations with input as _files(
		{"api": _hardened},
		{"api": {"cap_add": ["net_admin"]}},
	)
	count(violations) == 1
}

# SYS_ADMIN and ALL belong to compose_cap_add_sys_admin, which reports both
# wherever they appear. Repeating them here would put two findings on one line.
test_no_violation_for_capabilities_a_dedicated_rule_owns if {
	violations := adds_caps.violations with input as _files(
		{"api": _hardened},
		{"api": {"cap_add": ["SYS_ADMIN", "ALL"]}},
	)
	count(violations) == 0
}

# A narrow capability is the recommended fix, so reporting it would fire on the
# correct configuration.
test_no_violation_for_a_narrow_capability if {
	violations := adds_caps.violations with input as _files(
		{"api": _hardened},
		{"api": {"cap_add": ["NET_BIND_SERVICE"]}},
	)
	count(violations) == 0
}

test_no_violation_when_the_override_adds_nothing if {
	violations := adds_caps.violations with input as _files(
		{"api": _hardened},
		{"api": {"ports": ["8000:8000"]}},
	)
	count(violations) == 0
}

# Without cap_drop: ALL in the base there is no hardening being undone —
# compose_cap_add_sys_admin covers the capability on its own merits.
test_no_violation_when_the_base_drops_nothing if {
	violations := adds_caps.violations with input as _files(
		{"api": {"image": "app:1.0"}},
		{"api": {"cap_add": ["NET_ADMIN"]}},
	)
	count(violations) == 0
}

test_no_violation_without_an_override if {
	violations := adds_caps.violations with input as {"compose_files": [{
		"__docker_file": "compose.yml",
		"is_override": false,
		"services": {"api": _hardened},
	}]}
	count(violations) == 0
}

test_each_granted_capability_is_its_own_finding if {
	violations := adds_caps.violations with input as _files(
		{"api": _hardened},
		{"api": {"cap_add": ["SYS_PTRACE", "NET_ADMIN", "NET_BIND_SERVICE"]}},
	)
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
