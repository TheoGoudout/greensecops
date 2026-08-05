package greensecops.container_docker.energy.compose_missing_resource_limits_test

import data.greensecops.container_docker.energy.compose_missing_resource_limits
import rego.v1

_compose(services) := {"effective_compose_files": [{
	"__docker_file": "compose.yml",
	"services": services,
}]}

_service(extra) := object.union({"image": "app:1.0", "__start_line__": 2, "__end_line__": 6}, extra)

test_violation_when_no_limits_declared if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({})})
	count(violations) == 1
}

test_no_violation_with_deploy_resource_limits if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({"deploy": {"resources": {"limits": {"memory": "512M"}}}})})
	count(violations) == 0
}

test_no_violation_with_mem_limit_shorthand if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({"mem_limit": "512m"})})
	count(violations) == 0
}

test_no_violation_with_cpus_shorthand if {
	violations := compose_missing_resource_limits.violations with input as _compose({"worker": _service({"cpus": 1.5})})
	count(violations) == 0
}

# A service with neither image nor build runs nothing to limit.
test_no_violation_for_a_non_runnable_service if {
	violations := compose_missing_resource_limits.violations with input as _compose({"base": {"__start_line__": 2, "__end_line__": 3}})
	count(violations) == 0
}

test_violation_for_a_build_only_service if {
	violations := compose_missing_resource_limits.violations with input as _compose({"api": {
		"build": {"context": "."},
		"__start_line__": 2,
		"__end_line__": 5,
	}})
	count(violations) == 1
}

# The rule judges the merged configuration, never the files as they sit on
# disk. An override fragment restates only what it changes, so absence in it is
# not evidence of anything — it reaches this rule only through the merge.
test_no_violation_on_the_raw_files_of_a_merged_pair if {
	violations := compose_missing_resource_limits.violations with input as {
		"compose_files": [
			{
				"__docker_file": "compose.yml",
				"is_override": false,
				"services": {"worker": _service({})},
			},
			{
				"__docker_file": "compose.override.yml",
				"is_override": true,
				"services": {"worker": {"deploy": {"resources": {"limits": {"memory": "512M"}}}}},
			},
		],
		"effective_compose_files": [{
			"__docker_file": "compose.yml",
			"services": {"worker": _service({"deploy": {"resources": {"limits": {"memory": "512M"}}}})},
		}],
	}
	count(violations) == 0
}

# The converse: when nothing in the merged configuration supplies the limit,
# the base's own gap is reported — which the old is_override guard silenced
# for every target that happened to have an override file.
test_violation_when_the_merge_still_declares_no_limits if {
	violations := compose_missing_resource_limits.violations with input as {
		"compose_files": [
			{
				"__docker_file": "compose.yml",
				"is_override": false,
				"services": {"worker": _service({})},
			},
			{
				"__docker_file": "compose.override.yml",
				"is_override": true,
				"services": {"worker": {"environment": {"DEBUG": "1"}}},
			},
		],
		"effective_compose_files": [{
			"__docker_file": "compose.yml",
			"services": {"worker": _service({"environment": {"DEBUG": "1"}})},
		}],
	}
	count(violations) == 1
	some v in violations
	v.file_path == "compose.yml"
}

# A service the override introduces is not in the base file the merged document
# is named for, so the finding must cite the override — its line span is from
# there too, and the two have to agree.
test_a_service_only_the_override_declares_cites_the_override if {
	violations := compose_missing_resource_limits.violations with input as {"effective_compose_files": [{
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
	v.line_start == 12
}
