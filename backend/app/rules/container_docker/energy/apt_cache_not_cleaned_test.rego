package greensecops.container_docker.energy.apt_cache_not_cleaned_test

import data.greensecops.container_docker.energy.apt_cache_not_cleaned
import rego.v1

_run(value, flags) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [],
	"instructions": [{
		"instruction": "RUN",
		"value": value,
		"flags": flags,
		"heredoc": null,
		"stage": 0,
		"__start_line__": 4,
		"__end_line__": 4,
	}],
}]}

test_violation_when_lists_are_not_removed if {
	violations := apt_cache_not_cleaned.violations with input as _run("apt-get update && apt-get install -y curl", {})
	count(violations) == 1
}

test_no_violation_when_lists_are_removed if {
	violations := apt_cache_not_cleaned.violations with input as _run("apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*", {})
	count(violations) == 0
}

test_no_violation_with_an_apt_cache_mount if {
	violations := apt_cache_not_cleaned.violations with input as _run(
		"apt-get update && apt-get install -y curl",
		{"mount": "type=cache,target=/var/lib/apt"},
	)
	count(violations) == 0
}

test_no_violation_for_a_run_that_does_not_install if {
	violations := apt_cache_not_cleaned.violations with input as _run("apt-get update", {})
	count(violations) == 0
}

test_no_violation_for_a_non_apt_package_manager if {
	violations := apt_cache_not_cleaned.violations with input as _run("apk add --no-cache curl", {})
	count(violations) == 0
}
