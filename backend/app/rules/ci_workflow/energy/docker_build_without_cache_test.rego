package greensecops.ci_workflow.energy.docker_build_without_cache_test

import data.greensecops.ci_workflow.energy.docker_build_without_cache as build_without_cache
import rego.v1

_job(steps) := {"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": steps}}}

test_violation_for_the_build_action_without_cache if {
	violations := build_without_cache.violations with input as _job([{
		"uses": "docker/build-push-action@v6",
		"with": {"context": ".", "push": true},
	}])
	count(violations) == 1
	some v in violations
	v.job == "build"
}

test_no_violation_when_the_action_configures_a_cache if {
	violations := build_without_cache.violations with input as _job([{
		"uses": "docker/build-push-action@v6",
		"with": {"context": ".", "push": true, "cache-from": "type=gha", "cache-to": "type=gha,mode=max"},
	}])
	count(violations) == 0
}

# Either direction alone is enough to show a cache is in use.
test_no_violation_with_only_cache_from if {
	violations := build_without_cache.violations with input as _job([{
		"uses": "docker/build-push-action@v6",
		"with": {"context": ".", "cache-from": "type=registry,ref=ghcr.io/org/app:cache"},
	}])
	count(violations) == 0
}

test_no_violation_when_the_action_has_no_with_block if {
	violations := build_without_cache.violations with input as _job([{"uses": "docker/build-push-action@v6"}])
	count(violations) == 1
}

test_violation_for_a_shell_docker_build if {
	violations := build_without_cache.violations with input as _job([{"run": "docker build -t app:latest ."}])
	count(violations) == 1
}

test_violation_for_a_shell_buildx_build_without_cache if {
	violations := build_without_cache.violations with input as _job([{"run": "docker buildx build --platform linux/amd64 -t app:latest ."}])
	count(violations) == 1
}

test_no_violation_for_a_shell_buildx_build_with_cache if {
	violations := build_without_cache.violations with input as _job([{"run": "docker buildx build --cache-from type=gha --cache-to type=gha,mode=max -t app:latest ."}])
	count(violations) == 0
}

# Other docker verbs are not builds.
test_no_violation_for_docker_push if {
	violations := build_without_cache.violations with input as _job([{"run": "docker push app:latest"}])
	count(violations) == 0
}

test_no_violation_for_an_unrelated_action if {
	violations := build_without_cache.violations with input as _job([{"uses": "actions/checkout@v5"}])
	count(violations) == 0
}

test_each_uncached_build_is_its_own_finding if {
	violations := build_without_cache.violations with input as _job([
		{"uses": "docker/build-push-action@v6", "with": {"context": "./api"}},
		{"uses": "docker/build-push-action@v6", "with": {"context": "./web", "cache-from": "type=gha"}},
		{"run": "docker build -t tools ."},
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
