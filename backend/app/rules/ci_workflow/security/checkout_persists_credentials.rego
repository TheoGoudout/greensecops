# METADATA
# title: Checkout leaves the token in the git config
# description: A step uses actions/checkout without setting persist-credentials to false, so the workflow token is written into .git/config and stays there for every subsequent step in the job. Anything that runs afterwards can read it — a build script, a test helper, a postinstall hook in a dependency you have never looked at — and use it against the repository with whatever scopes the job holds. The token is already available to steps that need it through the env, so persisting it in the working tree adds reach without adding capability.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#             - run: npm ci && npm test
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#               with:
#                 persist-credentials: false
#             - run: npm ci && npm test
#     fix: |
#       Set `persist-credentials: false`. Where a later step genuinely needs to push, give it the token explicitly through `env` at that step rather than leaving it in the git config for the whole job — that way the grant is visible at the point of use and scoped to it.
package greensecops.ci_workflow.security.checkout_persists_credentials

import rego.v1

_persist_disabled(step) if step["with"]["persist-credentials"] == false

# YAML quoting turns it into a string often enough to be worth handling.
_persist_disabled(step) if lower(sprintf("%v", [step["with"]["persist-credentials"]])) == "false"

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps

	contains(object.get(step, "uses", ""), "actions/checkout")
	not _persist_disabled(step)

	violation := {
		"rule": "checkout_persists_credentials",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"line_start": object.get(step, "__start_line__", null),
		"line_end": object.get(step, "__end_line__", null),
		"message": sprintf("Checkout in job '%v' leaves the workflow token in .git/config, where every later step in the job can read it. Set persist-credentials: false.", [job_name]),
		"context": step.uses,
		"discriminator": sprintf("%v:%v", [job_name, step_index]),
	}
}
