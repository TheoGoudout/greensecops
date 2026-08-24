# METADATA
# title: Action pinned to a name that is both a branch and a tag
# description: "A step pins an action to a symbolic ref that exists upstream as a branch *and* as a tag. Git does not report the collision; it resolves it by a fixed precedence rule, so the step runs whichever of the two that rule selects rather than the one the author had in mind. The two are independent pointers — a tag that stays where it was put, and a branch anyone with write access can move — which means a repository can publish a tag `v1` and later create a branch `v1`, silently changing what every consumer of `@v1` executes."
# custom:
#   severity: medium
#   severity_weight: 1.0
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: example/action@v1
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: example/action@refs/tags/v1
#     action_metadata:
#       "example/action@v1":
#         lookup: ok
#         ref_kind: symbolic
#         symbolic_ref_kinds: ["branch", "tag"]
#       "example/action@refs/tags/v1":
#         lookup: ok
#         ref_kind: symbolic
#         symbolic_ref_kinds: ["tag"]
#     fix: |
#       Say which of the two you mean. `@refs/tags/v1` resolves the tag and `@refs/heads/v1` the branch, and both are accepted wherever a bare ref is. Do not silently swap the ref for a commit SHA as part of this change — that is a different decision, and the version comment beside a pin has to keep matching what it names.
package greensecops.ci_workflow.reliability.ref_confusion

import rego.v1

# Both kinds present, and the lookup that produced them succeeded. An absent
# `__actions__`, a failed lookup, or a one-element list all leave the body
# failing, so the rule is silent offline and whenever the API could not answer —
# the same construction `impostor_commit` uses and for the same reason.
_ambiguous(uses) if {
	meta := input.__actions__[uses]
	meta.lookup == "ok"
	meta.ref_kind == "symbolic"
	kinds := {kind | some kind in meta.symbolic_ref_kinds}
	kinds == {"branch", "tag"}
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	_ambiguous(uses)

	violation := {
		"rule": "ref_confusion",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' pins '%v' to a name that exists upstream as both a branch and a tag, so git picks between them by a precedence rule rather than by what was intended. Disambiguate the reference — 'refs/tags/<name>' for the tag, 'refs/heads/<name>' for the branch.", [job_name, uses]),
		"context": uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}

# A job calling a reusable workflow carries `uses:` itself and is pinned the
# same way, with the same collision.
violations contains violation if {
	some job_name, job in input.jobs
	uses := job.uses
	_ambiguous(uses)

	violation := {
		"rule": "ref_confusion",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"step": uses,
		"message": sprintf("Job '%v' calls '%v', whose ref exists upstream as both a branch and a tag, so git picks between them by a precedence rule rather than by what was intended. Disambiguate the reference — 'refs/tags/<name>' for the tag, 'refs/heads/<name>' for the branch.", [job_name, uses]),
		"context": uses,
		"discriminator": sprintf("%v:job-uses", [job_name]),
	}
}
