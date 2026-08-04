# METADATA
# title: Docker image built without a layer cache
# description: A step builds a Docker image without configuring a cache, so every run rebuilds every layer from scratch — including the dependency install that did not change. A CI runner starts empty, so unlike a developer's machine there is no local cache to fall back on and the cost is paid on every single run. This is the workflow-side counterpart of the Dockerfile ordering rules, which can only help once there is a cache for the ordering to preserve.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: docker/build-push-action@v6
#               with:
#                 context: .
#                 push: true
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: docker/build-push-action@v6
#               with:
#                 context: .
#                 push: true
#                 cache-from: type=gha
#                 cache-to: type=gha,mode=max
#     fix: |
#       Add cache-from and cache-to to the build action — type=gha uses the Actions cache and needs no other setup. For a plain docker build, use buildx with --cache-from/--cache-to against a registry.
package greensecops.ci_workflow.energy.docker_build_without_cache

import rego.v1

_action_name(uses) := split(uses, "@")[0] if is_string(uses)

_is_build_action(step) if _action_name(step.uses) == "docker/build-push-action"

_build_action_caches(step) if {
	some key in ["cache-from", "cache-to"]
	step["with"][key]
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_is_build_action(step)
	not _build_action_caches(step)

	violation := {
		"rule": "docker_build_without_cache",
		"severity": "medium",
		"category": "energy",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Job '%v' builds an image with no cache configured, so every layer is rebuilt on every run. Add cache-from and cache-to (type=gha needs no extra setup).", [job_name]),
		"context": "docker/build-push-action",
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}

# The shell equivalent. `docker buildx build` without --cache-from has the same
# problem, and a plain `docker build` cannot cache across runs at all.
_builds_in_shell(script) if regex.match(`(?m)\bdocker\s+(buildx\s+)?build\b`, script)

_shell_build_caches(script) if contains(script, "--cache-from")

_shell_build_caches(script) if contains(script, "--cache-to")

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	script := step.run
	is_string(script)
	_builds_in_shell(script)
	not _shell_build_caches(script)

	violation := {
		"rule": "docker_build_without_cache",
		"severity": "medium",
		"category": "energy",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Job '%v' runs docker build with no cache, so every layer is rebuilt on every run. Use buildx with --cache-from/--cache-to against a registry or the Actions cache.", [job_name]),
		"context": substring(script, 0, 300),
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
