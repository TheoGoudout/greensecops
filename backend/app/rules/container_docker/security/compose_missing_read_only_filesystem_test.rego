package greensecops.container_docker.security.compose_missing_read_only_filesystem_test

import data.greensecops.container_docker.security.compose_missing_read_only_filesystem as no_read_only
import rego.v1

_compose(services) := {"effective_compose_files": [{
	"__docker_file": "compose.yml",
	"is_override": false,
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_read_only_is_absent if {
	violations := no_read_only.violations with input as _compose({"api": _service({})})
	count(violations) == 1
	some v in violations
	v.service_name == "api"
	v.severity == "low"
}

test_no_violation_when_read_only_is_set if {
	violations := no_read_only.violations with input as _compose({"api": _service({"read_only": true})})
	count(violations) == 0
}

test_violation_when_read_only_is_explicitly_false if {
	violations := no_read_only.violations with input as _compose({"api": _service({"read_only": false})})
	count(violations) == 1
}

# compose_privileged_container reports the larger problem; adding a
# low-severity note beside it would be noise.
test_no_violation_for_a_privileged_service if {
	violations := no_read_only.violations with input as _compose({"agent": _service({"privileged": true})})
	count(violations) == 0
}

test_no_violation_for_a_non_runnable_service if {
	violations := no_read_only.violations with input as _compose({"base": {"__start_line__": 2, "__end_line__": 3}})
	count(violations) == 0
}

test_no_violation_for_a_null_service if {
	violations := no_read_only.violations with input as _compose({"api": null})
	count(violations) == 0
}

# The merged configuration is what counts, so a setting the override supplies
# resolves the finding.
test_no_violation_when_the_merge_supplies_read_only if {
	violations := no_read_only.violations with input as {
		"compose_files": [
			{"__docker_file": "compose.yml", "is_override": false, "services": {"api": _service({})}},
			{"__docker_file": "compose.override.yml", "is_override": true, "services": {"api": {"read_only": true}}},
		],
		"effective_compose_files": [{
			"__docker_file": "compose.yml",
			"services": {"api": _service({"read_only": true})},
		}],
	}
	count(violations) == 0
}

test_a_service_only_the_override_declares_cites_the_override if {
	violations := no_read_only.violations with input as {"effective_compose_files": [{
		"__docker_file": "compose.yml",
		"services": {"debugger": {
			"image": "busybox:1.36",
			"__docker_file": "compose.override.yml",
			"__start_line__": 12,
			"__end_line__": 14,
		}},
	}]}
	count(violations) == 1
	some v in violations
	v.file_path == "compose.override.yml"
}

test_each_service_is_its_own_finding if {
	violations := no_read_only.violations with input as _compose({
		"api": _service({}),
		"worker": _service({}),
		"db": _service({"read_only": true}),
	})
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
