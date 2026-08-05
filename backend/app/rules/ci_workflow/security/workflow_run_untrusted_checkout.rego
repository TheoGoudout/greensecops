# METADATA
# title: workflow_run job checks out the triggering commit
# description: A workflow triggered by workflow_run checks out the code from the run that triggered it. Like pull_request_target, a workflow_run workflow executes from the default branch with full repository secrets and a write token — but the commit it is checking out came from whatever ran before it, which for a fork's pull request is untrusted code. This is the pattern the "safe artifact upload" workaround is usually built on, and checking out the head is exactly the step that makes it unsafe again.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       on:
#         workflow_run:
#           workflows: ["CI"]
#           types: [completed]
#       jobs:
#         comment:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v5
#               with:
#                 ref: ${{ github.event.workflow_run.head_sha }}
#             - run: ./scripts/report.sh
#     good: |
#       on:
#         workflow_run:
#           workflows: ["CI"]
#           types: [completed]
#       jobs:
#         comment:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v5
#             - uses: actions/download-artifact@v5
#               with:
#                 run-id: ${{ github.event.workflow_run.id }}
#     fix: |
#       Do not check out the triggering commit in a workflow_run job. Check out the default branch for the scripts you trust, and bring anything the triggering run produced across as an artifact — data you then parse, rather than code you execute.
package greensecops.ci_workflow.security.workflow_run_untrusted_checkout

import rego.v1

_triggers_on_workflow_run if input.on.workflow_run

_triggers_on_workflow_run if {
	some trigger in input.on
	trigger == "workflow_run"
}

_checks_out_triggering_commit(step) if {
	contains(step.uses, "actions/checkout")
	ref := step["with"].ref
	is_string(ref)
	contains(ref, "github.event.workflow_run.head")
}

violations contains violation if {
	_triggers_on_workflow_run
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_checks_out_triggering_commit(step)

	violation := {
		"rule": "workflow_run_untrusted_checkout",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Job '%v' runs from the default branch with full secrets and checks out the commit that triggered it, which for a fork's pull request is untrusted code. Download an artifact instead of checking out the head.", [job_name]),
		"context": "workflow_run + head checkout",
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
