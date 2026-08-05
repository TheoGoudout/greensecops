package greensecops.container_docker.energy.compose_unbounded_log_files_test

import data.greensecops.container_docker.energy.compose_unbounded_log_files as unbounded_logs
import rego.v1

_compose(services) := {"effective_compose_files": [{
	"__docker_file": "compose.yml",
	"is_override": false,
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_no_logging_is_configured if {
	violations := unbounded_logs.violations with input as _compose({"api": _service({})})
	count(violations) == 1
	some v in violations
	v.service_name == "api"
}

test_no_violation_with_a_max_size if {
	violations := unbounded_logs.violations with input as _compose({"api": _service({"logging": {
		"driver": "json-file",
		"options": {"max-size": "10m", "max-file": "3"},
	}})})
	count(violations) == 0
}

# A driver declared without options still never rotates.
test_violation_when_the_driver_is_json_file_without_options if {
	violations := unbounded_logs.violations with input as _compose({"api": _service({"logging": {"driver": "json-file"}})})
	count(violations) == 1
}

# The `local` driver rotates by default, so naming it is itself a bound.
test_no_violation_for_the_local_driver if {
	violations := unbounded_logs.violations with input as _compose({"api": _service({"logging": {"driver": "local"}})})
	count(violations) == 0
}

# Shipping logs to a collector is a deliberate answer to the same question.
test_no_violation_when_logs_go_to_a_collector if {
	violations := unbounded_logs.violations with input as _compose({"api": _service({"logging": {
		"driver": "syslog",
		"options": {"syslog-address": "udp://logs.internal:514"},
	}})})
	count(violations) == 0
}

# A service with neither image nor build is not something that runs.
test_no_violation_for_a_non_runnable_service if {
	violations := unbounded_logs.violations with input as _compose({"api": {
		"__start_line__": 2,
		"__end_line__": 3,
	}})
	count(violations) == 0
}

test_violation_for_a_build_only_service if {
	violations := unbounded_logs.violations with input as _compose({"api": {
		"build": ".",
		"__start_line__": 2,
		"__end_line__": 4,
	}})
	count(violations) == 1
}

test_no_violation_for_a_null_service if {
	violations := unbounded_logs.violations with input as _compose({"api": null})
	count(violations) == 0
}

# An override fragment inherits logging from the base file, so its absence
# there proves nothing — the rule reads only the merged configuration, and the
# raw documents alongside it are for presence-based rules.
test_no_violation_on_the_raw_files_of_a_merged_pair if {
	violations := unbounded_logs.violations with input as {
		"compose_files": [
			{
				"__docker_file": "compose.yml",
				"is_override": false,
				"services": {"api": _service({})},
			},
			{
				"__docker_file": "compose.override.yml",
				"is_override": true,
				"services": {"api": {"logging": {"options": {"max-size": "10m"}}}},
			},
		],
		"effective_compose_files": [{
			"__docker_file": "compose.yml",
			"services": {"api": _service({"logging": {"options": {"max-size": "10m"}}})},
		}],
	}
	count(violations) == 0
}

test_each_unbounded_service_is_its_own_finding if {
	violations := unbounded_logs.violations with input as _compose({
		"api": _service({}),
		"worker": _service({}),
		"db": _service({"logging": {"options": {"max-size": "10m"}}}),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
