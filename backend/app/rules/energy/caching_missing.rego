# METADATA
# title: Missing dependency cache
# description: No cache action detected for package manager (pip, npm, gradle, cargo, etc.). Caching dependencies dramatically reduces build time and runner energy consumption.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/setup-node@v4
#               with:
#                 node-version: 20
#             - run: npm install
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/setup-node@v4
#               with:
#                 node-version: 20
#                 cache: npm
#             - run: npm install
#     fix: |
#       Enable caching on the setup action (e.g. cache: npm on actions/setup-node) or add an explicit actions/cache step before the install step.
package greensecops.energy.caching_missing

import rego.v1

# Maps action name (without @version) to the with: key that enables built-in caching.
_setup_action_cache_keys := {
	"actions/setup-node": "cache",
	"actions/setup-python": "cache",
	"actions/setup-java": "cache",
	"actions/setup-go": "cache",
	"actions/setup-dotnet": "cache",
	"astral-sh/setup-uv": "enable-cache",
}

_action_name(uses) := split(uses, "@")[0] if {
	is_string(uses)
}

_is_known_setup_action(uses) if {
	_setup_action_cache_keys[_action_name(uses)]
}

_has_cache_action(steps) if {
	some step in steps
	contains(step.uses, "actions/cache")
}

_has_cache_action(steps) if {
	some step in steps
	cache_key := _setup_action_cache_keys[_action_name(step.uses)]
	step["with"][cache_key]
}

_uses_package_manager(steps) if {
	some step in steps
	run := step.run
	some pm in ["npm ", "yarn ", "pip ", "pip3 ", "poetry ", "gradle ", "cargo ", "mvn ", "pnpm ", "bun ", "uv "]
	contains(run, pm)
}

_has_setup_step(steps) if {
	some step in steps
	_is_known_setup_action(step.uses)
}

_first_setup_idx(steps) := min({j | _is_known_setup_action(steps[j].uses)})

violations contains violation if {
	some job_name, job in input.jobs
	steps := job.steps
	_uses_package_manager(steps)
	not _has_cache_action(steps)
	setup_idx := _first_setup_idx(steps)
	setup_uses := steps[setup_idx].uses
	cache_key := _setup_action_cache_keys[_action_name(setup_uses)]
	violation := {
		"rule": "caching_missing",
		"severity": "high",
		"category": "energy",
		"job": job_name,
		"step": setup_uses,
		"step_index": setup_idx,
		"message": sprintf("Job '%v' installs dependencies without caching. Add '%v:' to %v.", [job_name, cache_key, setup_uses]),
		"context": null,
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	steps := job.steps
	_uses_package_manager(steps)
	not _has_cache_action(steps)
	not _has_setup_step(steps)
	violation := {
		"rule": "caching_missing",
		"severity": "high",
		"category": "energy",
		"job": job_name,
		"message": sprintf("Job '%v' installs dependencies without caching. Add an actions/cache step before the install step.", [job_name]),
		"context": null,
	}
}
