# METADATA
# title: Condition that is always true
# description: "An if: is written so that it always evaluates to true, so the gate it looks like never gates anything. The common cause is wrapping the whole condition in ${{ }} together with other text, which makes the result a non-empty string rather than a boolean — GitHub then coerces it to true. The step runs on every event, including the ones the condition was added to exclude, and nothing about the run looks wrong."
# custom:
#   severity: high
#   severity_weight: 1.8
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - if: ${{ github.event_name == 'push' }} && ${{ github.ref == 'refs/heads/main' }}
#               run: ./deploy.sh
#     good: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           steps:
#             - if: github.event_name == 'push' && github.ref == 'refs/heads/main'
#               run: ./deploy.sh
#     fix: |
#       Write the condition without the ${{ }} wrapper — if: accepts an expression directly. Where a wrapper is genuinely wanted, it has to enclose the whole condition exactly once, so the result is the boolean itself rather than a string containing one.
package greensecops.ci_workflow.reliability.unsound_condition

import rego.v1

# Two or more `${{ }}` groups in one condition. Each is substituted into a
# string, and the surrounding operators become literal text, so the result is a
# non-empty string — always true.
_multiple_expression_groups(condition) if {
	is_string(condition)
	count(regex.find_n(`\$\{\{`, condition, -1)) > 1
}

# A single wrapper with text outside it, e.g. `${{ a }} && b`. Same failure:
# the whole thing is a string.
_expression_with_trailing_text(condition) if {
	is_string(condition)
	count(regex.find_n(`\$\{\{`, condition, -1)) == 1
	trimmed := trim_space(condition)
	startswith(trimmed, "${{")
	not endswith(trimmed, "}}")
}

_is_unsound(condition) if _multiple_expression_groups(condition)

_is_unsound(condition) if _expression_with_trailing_text(condition)

violations contains violation if {
	some job_name, job in input.jobs
	_is_unsound(job["if"])

	violation := {
		"rule": "unsound_condition",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Job '%v' has an if: built from more than one ${{ }} group, so it evaluates to a non-empty string rather than a boolean and is always true. The job runs on every event.", [job_name]),
		"context": job["if"],
		"discriminator": sprintf("%v:job-if", [job_name]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_is_unsound(step["if"])

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "unsound_condition",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' has an if: built from more than one ${{ }} group, so it evaluates to a non-empty string rather than a boolean and is always true. The step runs unconditionally.", [step_label, job_name]),
		"context": step["if"],
		"discriminator": sprintf("%v:%v:step-if", [job_name, step_index]),
	}
}
