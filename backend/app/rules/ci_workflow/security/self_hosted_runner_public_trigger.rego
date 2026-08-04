# METADATA
# title: Self-hosted runner reachable from a fork pull request
# description: A job runs on a self-hosted runner in a workflow triggered by pull requests, so a fork's code executes on a machine the repository owns. Unlike a GitHub-hosted runner, that machine is not destroyed afterwards — anything the fork's build writes to disk, installs, or leaves running persists into the next job, including one from a different repository if the runner is shared. GitHub's own documentation recommends against this combination for public repositories.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       on:
#         pull_request:
#       jobs:
#         build:
#           runs-on: self-hosted
#           steps:
#             - uses: actions/checkout@v5
#     good: |
#       on:
#         pull_request:
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v5
#     fix: |
#       Run pull request builds on GitHub-hosted runners, which are destroyed after each job. If a self-hosted runner is unavoidable, require approval for outside contributors and use ephemeral runners so no state survives a job.
package greensecops.ci_workflow.security.self_hosted_runner_public_trigger

import rego.v1

_pr_triggers := {"pull_request", "pull_request_target"}

_has_pr_trigger if {
	some trigger in _pr_triggers
	input.on[trigger]
}

# `on: [push, pull_request]` is a list of names rather than a mapping.
_has_pr_trigger if {
	some trigger in input.on
	trigger in _pr_triggers
}

_is_self_hosted(label) if {
	is_string(label)
	lower(label) == "self-hosted"
}

# `runs-on` is either a single label or a list of them, and a self-hosted
# runner is normally selected by combining `self-hosted` with more labels.
_runs_self_hosted(job) if _is_self_hosted(job["runs-on"])

_runs_self_hosted(job) if {
	some label in job["runs-on"]
	_is_self_hosted(label)
}

# The object form: `runs-on: {group: ..., labels: [...]}`.
_runs_self_hosted(job) if {
	some label in job["runs-on"].labels
	_is_self_hosted(label)
}

violations contains violation if {
	_has_pr_trigger
	some job_name, job in input.jobs
	_runs_self_hosted(job)

	violation := {
		"rule": "self_hosted_runner_public_trigger",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' runs a pull request build on a self-hosted runner, so a fork's code executes on a machine you own and whatever it leaves behind survives into the next job.", [job_name]),
		"context": "self-hosted",
		"discriminator": job_name,
	}
}
