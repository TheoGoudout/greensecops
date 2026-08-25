# METADATA
# title: Action reference is not pinned to a commit SHA
# description: "A step, or a job calling a reusable workflow, references an action by a tag or a branch rather than by a full 40-character commit SHA. Every ref that is not a SHA is mutable: a tag can be moved to a different commit by whoever owns the repository, and a branch moves on every push, so the code that ran yesterday is not necessarily the code that runs today. This covers first-party and third-party actions alike, and semver tags as well as bare major tags — `@v4.1.1` is exactly as movable as `@v4`. Local (`./`) and `docker://` references are excluded: neither is pinnable this way."
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v4
#             - uses: some-org/deploy-action@v2.1.0
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
#             - uses: some-org/deploy-action@a81bbbf8298c0fa03ea29cdc473d45769f953675 # v2.1.0
#     fix: |
#       Replace each ref with the full commit SHA the tag currently points at, and keep the version in a trailing comment so a reader still knows which release it is. Dependabot and Renovate both update SHA pins with the comment intact, so this costs nothing on an ongoing basis.
package greensecops.ci_workflow.reliability.unpinned_actions

import data.greensecops.lib.workflow as wf
import rego.v1

# Absorbed `untrusted_actions`, which asked the same question of a subset of
# refs and disagreed with this rule about the answer. That rule reported any
# non-`actions/`, non-`github/` action that was not SHA-pinned; this one
# reported `@main`, `@master`, `@latest` and bare `@vN` for any owner. Between
# them, `some-org/action@v3` produced two findings for one problem while
# `actions/checkout@v4.1.1` produced none — a full semver tag is a tag, and
# tags move.
#
# So the question is asked once, of every ref, in the only form that is
# actually true: is this a 40-character commit SHA?

# Neither of these can carry a commit SHA, so demanding one asks for something
# the author cannot write. A local action is versioned by the repository it
# lives in; a Docker action is pinned by digest, which is what
# `unpinned_container_image` asks of the images a job runs.
_unpinnable(uses) if wf.is_local_ref(uses)

_unpinnable(uses) if wf.is_docker_ref(uses)

_reportable(uses) if {
	is_string(uses)
	not _unpinnable(uses)
	not wf.is_sha_pin(uses)
}

# The ref as written, for the message. Undefined for a bare `owner/repo` with
# no `@` at all, which GitHub resolves to the default branch — the most mutable
# ref there is, and worth naming as such.
_ref_label(uses) := wf.action_ref(uses)

_ref_label(uses) := "the default branch" if not wf.action_ref(uses)

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	_reportable(uses)

	violation := {
		"rule": "unpinned_actions",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"line_start": object.get(step, "__start_line__", null),
		"line_end": object.get(step, "__end_line__", null),
		"message": sprintf("Step in job '%v' uses '%v', pinned to %v rather than a commit SHA. That ref can be moved to different code without any change here.", [job_name, uses, _ref_label(uses)]),
		"context": uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}

# A job that calls a reusable workflow runs that workflow's steps with this
# repository's secrets, so an unpinned `uses:` here has the same reach as an
# unpinned action and a larger blast radius. The job has no `steps`, so it
# needs its own clause and its own discriminator.
violations contains violation if {
	some job_name, job in input.jobs
	uses := job.uses
	_reportable(uses)

	violation := {
		"rule": "unpinned_actions",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"step": uses,
		"line_start": object.get(job, "__start_line__", null),
		"line_end": object.get(job, "__end_line__", null),
		"message": sprintf("Job '%v' calls the reusable workflow '%v', pinned to %v rather than a commit SHA. The called workflow runs with this repository's secrets.", [job_name, uses, _ref_label(uses)]),
		"context": uses,
		"discriminator": sprintf("%v:job-uses", [job_name]),
	}
}
