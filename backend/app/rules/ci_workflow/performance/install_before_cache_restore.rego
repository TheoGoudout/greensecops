# METADATA
# title: Dependencies are installed before the cache is restored
# description: A job installs dependencies in a step that runs before actions/cache restores them, so the cache is populated but never used — every run downloads the full dependency tree and then writes it to a cache the next run will also ignore. The workflow looks cached, the cache-hit metric even looks healthy, and the runtime never improves. It is a quietly expensive mistake because nothing fails and nothing warns, and on a busy repository it is minutes of runner time and the energy behind it on every single run.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#             - run: npm ci
#             - uses: actions/cache@v4
#               with:
#                 path: ~/.npm
#                 key: npm-lock
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#             - uses: actions/cache@v4
#               with:
#                 path: ~/.npm
#                 key: npm-lock
#             - run: npm ci
#     fix: |
#       Move the cache step above the install. Better still, use the cache built into the setup action for your language — `actions/setup-node` with `cache: npm` gets the ordering right by construction and needs no separate step at all.
package greensecops.ci_workflow.performance.install_before_cache_restore

import rego.v1

_install_commands := [
	"npm ci",
	"npm install",
	"yarn install",
	"pnpm install",
	"pip install",
	"poetry install",
	"bundle install",
	"go mod download",
	"cargo fetch",
	"composer install",
	"uv sync",
]

_is_install(step) if {
	run := step.run
	is_string(run)
	some command in _install_commands
	contains(run, command)
}

_is_cache_restore(step) if {
	uses := object.get(step, "uses", "")
	contains(uses, "actions/cache@")
}

violations contains violation if {
	some job_name, job in input.jobs
	steps := job.steps

	some install_index, install_step in steps
	_is_install(install_step)

	some cache_index, cache_step in steps
	_is_cache_restore(cache_step)

	cache_index > install_index

	violation := {
		"rule": "install_before_cache_restore",
		"severity": "medium",
		"category": "performance",
		"job": job_name,
		"step_index": cache_index,
		"line_start": object.get(cache_step, "__start_line__", null),
		"line_end": object.get(cache_step, "__end_line__", null),
		"message": sprintf("Job '%v' restores its cache at step %v, after installing dependencies at step %v — so the cache is written every run and read by nothing. Move the cache step above the install.", [job_name, cache_index, install_index]),
		"context": object.get(cache_step, "uses", ""),
		"discriminator": sprintf("%v:%v", [job_name, cache_index]),
	}
}
