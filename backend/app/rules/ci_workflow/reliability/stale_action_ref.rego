# METADATA
# title: Pin to a commit GitHub cannot find
# description: "A step pins an action to a commit the named repository does not have at all. The run fails at checkout of the action, every time, for everyone — a typo in the SHA, a force-pushed history, or a repository deleted and recreated under the same name. This is the sibling of impostor_commit and deliberately disjoint from it: there the object exists but is on no ref, here GitHub has never heard of it."
# custom:
#   severity: medium
#   severity_weight: 1.2
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@1111111111111111111111111111111111111111
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
#     action_metadata:
#       "actions/checkout@1111111111111111111111111111111111111111":
#         lookup: ok
#         ref_kind: sha
#         commit_exists: false
#       "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1":
#         lookup: ok
#         ref_kind: sha
#         commit_exists: true
#         reachability: reachable
#     fix: |
#       Resolve the tag you meant to a commit that exists and pin to that. Where the upstream repository rewrote history or was recreated, check what the new commit actually contains before repinning — a SHA that stopped existing is a change of code, not a change of address.
package greensecops.ci_workflow.reliability.stale_action_ref

import rego.v1

# `commit_exists == false` is only meaningful when the repository itself was
# read successfully. A private, renamed or rate-limited repository reports the
# same 404 as a missing commit, so without the `lookup == "ok"` guard every
# internal composite action would fire this on every scan.
_reported(uses) := meta if {
	meta := input.__actions__[uses]
	meta.lookup == "ok"
	meta.commit_exists == false
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	_reported(uses)

	violation := {
		"rule": "stale_action_ref",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' pins '%v' to a commit the repository does not have. The run fails when it tries to fetch the action.", [job_name, uses]),
		"context": uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
