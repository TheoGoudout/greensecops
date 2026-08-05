package greensecops.container_docker.security.compose_override_weakens_user_test

import data.greensecops.container_docker.security.compose_override_weakens_user as weakens_user
import rego.v1

# This rule reads the files as they sit on disk, not the merge — by the time
# the documents are merged the override has already won, and the conflict this
# rule reports is no longer visible.

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

test_violation_when_the_override_sets_root if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({"user": "10001"})},
		{"api": {"user": "root"}},
	)
	count(violations) == 1
	some v in violations
	v.service_name == "api"
	v.file_path == "compose.override.yml"
	v.severity == "high"
}

test_violation_for_the_numeric_zero_spelling if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({"user": "10001"})},
		{"api": {"user": 0}},
	)
	count(violations) == 1
}

test_violation_for_the_uid_gid_spelling if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({"user": "10001:10001"})},
		{"api": {"user": "0:0"}},
	)
	count(violations) == 1
}

test_no_violation_when_the_override_keeps_an_unprivileged_user if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({"user": "10001"})},
		{"api": {"user": "1000:1000"}},
	)
	count(violations) == 0
}

test_no_violation_when_the_override_does_not_touch_the_user if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({"user": "10001"})},
		{"api": {"ports": ["8000:8000"]}},
	)
	count(violations) == 0
}

# Nothing was weakened if the base never set a user — container_runs_as_root
# and the image's own USER are that service's concern.
test_no_violation_when_the_base_sets_no_user if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({})},
		{"api": {"user": "root"}},
	)
	count(violations) == 0
}

test_no_violation_when_the_base_itself_runs_as_root if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({"user": "root"})},
		{"api": {"user": "root"}},
	)
	count(violations) == 0
}

test_no_violation_for_a_service_the_base_does_not_declare if {
	violations := weakens_user.violations with input as _files(
		{"api": _service({"user": "10001"})},
		{"debugger": {"image": "busybox", "user": "root"}},
	)
	count(violations) == 0
}

test_no_violation_without_an_override if {
	violations := weakens_user.violations with input as {"compose_files": [{
		"__docker_file": "compose.yml",
		"is_override": false,
		"services": {"api": _service({"user": "10001"})},
	}]}
	count(violations) == 0
}

test_each_weakened_service_is_its_own_finding if {
	violations := weakens_user.violations with input as _files(
		{
			"api": _service({"user": "10001"}),
			"worker": _service({"user": "10001"}),
			"db": _service({"user": "10001"}),
		},
		{
			"api": {"user": "root"},
			"worker": {"user": "0"},
			"db": {"user": "10001"},
		},
	)
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
