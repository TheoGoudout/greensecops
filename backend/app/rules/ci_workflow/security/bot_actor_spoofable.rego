# METADATA
# title: Spoofable bot identity check
# description: "A condition gates privileged work on github.actor or github.triggering_actor matching a bot name. The actor is whoever caused the event, not whoever wrote the code — anyone able to trigger the workflow on a bot-authored pull request satisfies the check, and on pull_request_target the branch contents are the contributor's. A gate that decides whether to auto-merge or to hand over a token needs an identity the requester cannot choose."
# custom:
#   severity: high
#   severity_weight: 2.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       on:
#         pull_request_target:
#       jobs:
#         automerge:
#           if: github.actor == 'dependabot[bot]'
#           runs-on: ubuntu-latest
#           steps:
#             - run: gh pr merge --auto
#     good: |
#       on:
#         pull_request_target:
#       jobs:
#         automerge:
#           if: github.event.pull_request.user.login == 'dependabot[bot]'
#           runs-on: ubuntu-latest
#           steps:
#             - run: gh pr merge --auto
#     fix: |
#       Gate on the pull request's author instead — github.event.pull_request.user.login — or, for Dependabot specifically, verify the metadata with dependabot/fetch-metadata rather than trusting a name. The actor field answers "who pressed the button", which is not the question a privilege gate is asking.
package greensecops.ci_workflow.security.bot_actor_spoofable

import rego.v1

_bot_names := [
	"dependabot",
	"renovate",
	"github-actions",
	"pre-commit-ci",
	"copilot",
	"mergify",
]

# `github.actor` is who triggered the run. On a bot-opened pull request anyone
# who can re-run, label or comment becomes the actor while the branch contents
# stay the contributor's, so the name proves nothing about the code.
_spoofable_actor_check(condition) if {
	is_string(condition)
	regex.match(`github\.(actor|triggering_actor)`, condition)
	some bot in _bot_names
	contains(lower(condition), bot)
}

violations contains violation if {
	some job_name, job in input.jobs
	_spoofable_actor_check(job["if"])

	violation := {
		"rule": "bot_actor_spoofable",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' gates on github.actor matching a bot name. The actor is whoever triggered the run, not whoever wrote the code, so anyone who can re-run or comment on a bot's pull request passes this check. Gate on github.event.pull_request.user.login instead.", [job_name]),
		"context": "github.actor",
		"discriminator": sprintf("%v:job-if", [job_name]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_spoofable_actor_check(step["if"])

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "bot_actor_spoofable",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' gates on github.actor matching a bot name. The actor is whoever triggered the run, not whoever wrote the code. Gate on github.event.pull_request.user.login instead.", [step_label, job_name]),
		"context": "github.actor",
		"discriminator": sprintf("%v:%v:step-if", [job_name, step_index]),
	}
}
