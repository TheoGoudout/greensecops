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

_has_cache_action(steps) if {
	some step in steps
	uses := step.uses
	contains(uses, "actions/cache")
}

_has_cache_action(steps) if {
	some step in steps
	uses := step.uses
	startswith(uses, "actions/setup-")
	step["with"].cache
}

_uses_package_manager(steps) if {
	some step in steps
	run := step.run
	some pm in ["npm ", "yarn ", "pip ", "pip3 ", "poetry ", "gradle ", "cargo ", "mvn ", "pnpm ", "bun "]
	contains(run, pm)
}

violations contains violation if {
	some job_name, job in input.jobs
	steps := job.steps
	_uses_package_manager(steps)
	not _has_cache_action(steps)
	violation := {
		"rule": "caching_missing",
		"severity": "high",
		"category": "energy",
		"job": job_name,
		"message": sprintf("Job '%v' installs dependencies without caching. Add actions/cache or use setup-* with cache: true.", [job_name]),
		"context": null,
	}
}
