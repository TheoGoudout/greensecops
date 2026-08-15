# METADATA
# title: Action from an archived repository
# description: "A step uses an action whose repository is archived. Nothing more will be released from it — no bug fix, and no security patch when one is needed — so the pin is permanent whether or not that was the intention. Archiving is also the usual last step before a repository is deleted or transferred, at which point the reference stops resolving."
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
#             - uses: abandoned-org/old-action@8a940392f4c65274539453a5d5a76d9550203ac1
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
#     action_metadata:
#       "abandoned-org/old-action@8a940392f4c65274539453a5d5a76d9550203ac1":
#         lookup: ok
#         ref_kind: sha
#         archived: true
#       "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1":
#         lookup: ok
#         ref_kind: sha
#         archived: false
#     fix: |
#       Move to a maintained equivalent, or vendor the action into this repository as a composite action so the code is one you can patch. Where neither is worth it, record the decision next to the pin — an archived dependency is a choice, and the next reader should be able to tell it was made deliberately.
package greensecops.ci_workflow.maintainability.archived_action

import rego.v1

_reported(uses) := meta if {
	meta := input.__actions__[uses]
	meta.lookup == "ok"
	meta.archived == true
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	uses := step.uses
	_reported(uses)

	violation := {
		"rule": "archived_action",
		"severity": "medium",
		"category": "maintainability",
		"job": job_name,
		"step": uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' uses '%v', whose repository is archived — no fixes and no security patches will be published for it.", [job_name, uses]),
		"context": uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
