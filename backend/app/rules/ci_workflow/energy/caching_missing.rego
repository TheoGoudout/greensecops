# METADATA
# title: Missing dependency cache
# description: "A job installs dependencies without any cache. Every run re-downloads and rebuilds the same tree, which is usually the largest single block of runner time in a workflow and the easiest to remove. Detection keys on install commands specifically — running a task through a package manager is not installing, so 'npm run lint' and 'uv run pytest' do not count."
# custom:
#   severity: high
#   severity_weight: 1.5
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/setup-node@v4
#               with:
#                 node-version: 20
#             - run: npm ci
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/setup-node@v4
#               with:
#                 node-version: 20
#                 cache: npm
#             - run: npm ci
#     fix: |
#       Enable caching on the setup action (cache: npm on actions/setup-node, cache: pip on actions/setup-python) or add an actions/cache step keyed on the lockfile before the install step.
package greensecops.ci_workflow.energy.caching_missing

import data.greensecops.lib.workflow as wf
import rego.v1

# Maps a setup action to the `with:` key that turns its built-in cache on.
_setup_action_cache_keys := {
	"actions/setup-node": "cache",
	"actions/setup-python": "cache",
	"actions/setup-java": "cache",
	"actions/setup-go": "cache",
	"actions/setup-dotnet": "cache",
	"astral-sh/setup-uv": "enable-cache",
	"ruby/setup-ruby": "bundler-cache",
}

# Actions that cache unconditionally, with no `with:` key needed. Not
# recognising these was a false-positive source: a Rust job using
# Swatinem/rust-cache caches perfectly well and was reported as having no cache
# at all.
#
# Setup actions deliberately do NOT belong here — their caching is off until the
# key in `_setup_action_cache_keys` is set, so listing them would make every
# `actions/setup-node@v4` with no `cache:` count as cached, which is exactly the
# case this rule exists to report.
_caching_actions := {
	"actions/cache",
	"actions/cache/restore",
	"Swatinem/rust-cache",
	"buildjet/cache",
}

# Commands that actually install a dependency tree. The previous version matched
# the bare tool name with a trailing space — `"npm "`, `"uv "`, `"pip "` — so
# `uv run pytest` and `npm run lint` counted as installing dependencies. In a
# uv-based repository that matched essentially every step.
_install_commands := [
	"npm ci",
	"npm install",
	"npm i ",
	"yarn install",
	"pnpm install",
	"pnpm i ",
	"bun install",
	"pip install",
	"pip3 install",
	"pip download",
	"python -m pip install",
	"poetry install",
	"uv sync",
	"uv pip install",
	"cargo build",
	"cargo install",
	"cargo fetch",
	"go mod download",
	"bundle install",
	"composer install",
	"mvn install",
	"mvn package",
	"gradle build",
	"gradle assemble",
]

_installs_dependencies(steps) if {
	some step in steps
	run := step.run
	is_string(run)
	some cmd in _install_commands
	contains(run, cmd)
}

_is_known_setup_action(uses) if _setup_action_cache_keys[wf.action_name(uses)]

# A caching action is present.
_has_cache(steps) if {
	some step in steps
	wf.action_name(step.uses) in _caching_actions
	not _cache_explicitly_disabled(step)
}

# A setup action with its cache key set.
_has_cache(steps) if {
	some step in steps
	cache_key := _setup_action_cache_keys[wf.action_name(step.uses)]
	step["with"][cache_key]
}

# setup-uv caches by default from v6; only an explicit opt-out disables it.
_has_cache(steps) if {
	some step in steps
	wf.action_name(step.uses) == "astral-sh/setup-uv"
	not _cache_explicitly_disabled(step)
}

_cache_explicitly_disabled(step) if step["with"]["enable-cache"] == false

_cache_explicitly_disabled(step) if step["with"].cache == false

_first_setup_idx(steps) := min({j | _is_known_setup_action(steps[j].uses)})

violations contains violation if {
	some job_name, job in input.jobs
	steps := job.steps
	_installs_dependencies(steps)
	not _has_cache(steps)
	setup_idx := _first_setup_idx(steps)
	setup_uses := steps[setup_idx].uses
	cache_key := _setup_action_cache_keys[wf.action_name(setup_uses)]
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
	_installs_dependencies(steps)
	not _has_cache(steps)
	not _has_setup_step(steps)
	violation := {
		"rule": "caching_missing",
		"severity": "high",
		"category": "energy",
		"job": job_name,
		"message": sprintf("Job '%v' installs dependencies without caching. Add an actions/cache step keyed on the lockfile before the install step.", [job_name]),
		"context": null,
	}
}

_has_setup_step(steps) if {
	some step in steps
	_is_known_setup_action(step.uses)
}
