# METADATA
# title: Untrusted input interpolated into a run script
# description: A run step interpolates a GitHub expression whose value an outside contributor controls — a pull request title or body, a branch name, an issue comment. The expression is substituted into the shell script before the shell sees it, so the value is not data being passed to a command, it is script text. A branch named with a backtick-quoted command therefore executes on the runner with whatever the job's token can reach.
# custom:
#   severity: critical
#   severity_weight: 4.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         greet:
#           runs-on: ubuntu-latest
#           steps:
#             - run: echo "Thanks for ${{ github.event.pull_request.title }}"
#     good: |
#       jobs:
#         greet:
#           runs-on: ubuntu-latest
#           env:
#             PR_TITLE: ${{ github.event.pull_request.title }}
#           steps:
#             - run: echo "Thanks for $PR_TITLE"
#     fix: |
#       Pass the value through an environment variable and read it from the shell. The expression is then substituted into the variable's value rather than into the script, so the shell treats it as data no matter what it contains.
package greensecops.ci_workflow.security.script_injection_expression

import rego.v1

# Fields an outside contributor can set. Deliberately not `github.actor` or
# `github.repository` — those are attacker-*influenced* only in ways that
# GitHub already constrains, and flagging them buries the real ones.
_untrusted_contexts := [
	`github\.event\.pull_request\.title`,
	`github\.event\.pull_request\.body`,
	`github\.event\.pull_request\.head\.ref`,
	`github\.event\.pull_request\.head\.label`,
	`github\.event\.pull_request\.head\.repo\.[a-z_.]+`,
	`github\.event\.issue\.title`,
	`github\.event\.issue\.body`,
	`github\.event\.comment\.body`,
	`github\.event\.review\.body`,
	`github\.event\.review_comment\.body`,
	`github\.event\.discussion\.title`,
	`github\.event\.discussion\.body`,
	`github\.event\.head_commit\.message`,
	`github\.event\.head_commit\.author\.(name|email)`,
	`github\.event\.commits\[[0-9]+\]\.message`,
	`github\.event\.workflow_run\.head_branch`,
	`github\.head_ref`,
]

_interpolates_untrusted(script) := context if {
	some pattern in _untrusted_contexts
	matches := regex.find_n(sprintf(`\$\{\{\s*%v\s*\}\}`, [pattern]), script, 1)
	count(matches) > 0
	context := matches[0]
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	script := step.run
	is_string(script)
	context := _interpolates_untrusted(script)

	violation := {
		"rule": "script_injection_expression",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Job '%v' interpolates %v straight into a run script. The value is substituted as script text before the shell runs, so anyone who can set it can execute commands on the runner.", [job_name, context]),
		"context": context,
		"discriminator": sprintf("%v:%v:%v", [job_name, step_index, context]),
	}
}
