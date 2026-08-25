# METADATA
# title: Publishing job restores a shared cache
# description: "A job that builds a release restores a GitHub Actions cache. Cache entries are writable from any branch of the repository, and the cache service does not distinguish who wrote one — a pull request branch can seed an entry that a later run on a tag restores. The restored bytes then become part of a signed, published artifact. Every other job can afford a poisoned cache because its output is thrown away; a release job cannot, because its output is what users install."
# custom:
#   severity: high
#   severity_weight: 1.5
#   detection: static_analysis
#   examples:
#     bad: |
#       on:
#         push:
#           tags: ["v*"]
#       jobs:
#         publish:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
#             - uses: actions/cache@1bd1e32a3bdc45362d1e726936510720a7c30a57
#               with:
#                 path: ~/.npm
#                 key: npm-${{ hashFiles('package-lock.json') }}
#             - run: npm ci && npm publish
#     good: |
#       on:
#         push:
#           tags: ["v*"]
#       jobs:
#         publish:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
#             - run: npm ci && npm publish
#     fix: |
#       Take the cache out of the publishing job. A release build runs rarely and its inputs are pinned, so the cache saves little and risks the one artifact that must be reproducible: drop the `actions/cache` step, or set the setup action's cache input to false. Where the build genuinely needs the speed, split it — cache freely in a job whose output is discarded, and rebuild from scratch in the job that publishes.
package greensecops.ci_workflow.security.cache_poisoning_release

import data.greensecops.lib.workflow as wf
import rego.v1

# What makes a run a *publishing* run, narrowly. `release` and a tag-filtered
# `push` are the two triggers that say "this run's output is what ships" without
# needing to guess. `workflow_dispatch` is deliberately not here: most manually
# dispatched workflows are test runs, and firing on all of them would report a
# cache that never reaches a published artifact.
_publishing_trigger if wf.has_trigger("release")

_publishing_trigger if {
	is_object(input.on)
	input.on.push.tags
}

# Actions whose whole purpose is restoring a cache. No input to inspect — using
# them at all is the finding.
_always_caches(uses) if {
	name := lower(wf.action_name(uses))
	some prefix in ["actions/cache", "swatinem/rust-cache", "buildjet/cache", "runs-on/cache"]
	startswith(name, prefix)
}

# A `setup-*` action told to cache. Keyed on the input being present and truthy,
# never on its absence: several setup actions cache by default, and reporting
# "you did not write cache: false" would fire on every publishing job that uses
# one. That is a real gap, and it is the deliberate one — a missed finding beats
# a finding the author cannot act on. See docs/rule-authoring.rst, "Absent is
# not false".
_configured_to_cache(step) if {
	value := step["with"].cache
	not lower(sprintf("%v", [value])) in {"false", "", "none"}
}

_configured_to_cache(step) if step["with"]["cache-dependency-path"]

_restores_cache(step) if _always_caches(step.uses)

_restores_cache(step) if {
	is_string(step.uses)
	_configured_to_cache(step)
}

violations contains violation if {
	_publishing_trigger
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_restores_cache(step)

	violation := {
		"rule": "cache_poisoning_release",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Job '%v' runs on a release or tag push and restores a cache with '%v'. Any branch of this repository can write the entry it reads, so a pull request can plant bytes that end up inside the published artifact. Remove the cache from the publishing job, or set its cache input to false and rebuild from scratch.", [job_name, step.uses]),
		"context": step.uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
