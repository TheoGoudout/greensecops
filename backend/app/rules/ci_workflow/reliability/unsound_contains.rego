# METADATA
# title: contains() given a joined string instead of a list
# description: "A condition calls `contains()` with a space- or comma-joined string as its haystack, as though it were a set of allowed values. On a string, `contains()` is substring matching — so the check passes for anything that happens to appear inside the joined text, including a prefix of one entry and any span that straddles two of them. A branch called `refs/heads/ma` satisfies `contains('refs/heads/main refs/heads/dev', github.ref)`. GitHub expressions have a real list literal, and on a list `contains()` compares elements."
# custom:
#   severity: medium
#   severity_weight: 1.0
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           if: contains('refs/heads/main refs/heads/release', github.ref)
#           steps:
#             - run: ./deploy.sh
#     good: |
#       jobs:
#         deploy:
#           runs-on: ubuntu-latest
#           if: contains(fromJSON('["refs/heads/main", "refs/heads/release"]'), github.ref)
#           steps:
#             - run: ./deploy.sh
#     fix: |
#       Replace the joined string with a real list, so `contains()` compares whole elements: `contains(fromJSON('["a", "b"]'), value)`. For exactly two alternatives an explicit comparison is plainer still — `github.ref == 'refs/heads/main' || github.ref == 'refs/heads/release'`.
package greensecops.ci_workflow.reliability.unsound_contains

import rego.v1

# The haystack is a *string literal* holding a separator — that is what says
# "this was meant to be a list". `contains(github.event.head_commit.message,
# 'skip ci')` is the legitimate substring use and has no literal in the first
# position, so it never matches.
_UNSOUND := `contains\s*\(\s*'[^']*[\s,][^']*'\s*,`

_unsound(text) if {
	is_string(text)
	regex.match(_UNSOUND, text)
}

violations contains violation if {
	some job_name, job in input.jobs
	_unsound(job["if"])

	violation := {
		"rule": "unsound_contains",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Job '%v' has an if: calling contains() on a joined string, which is substring matching rather than membership — a value that is merely a prefix of one entry, or spans two of them, passes the check. Use a list: contains(fromJSON('[\"a\", \"b\"]'), value).", [job_name]),
		"context": job["if"],
		"discriminator": sprintf("%v:job-if", [job_name]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_unsound(step["if"])

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "unsound_contains",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' has an if: calling contains() on a joined string, which is substring matching rather than membership — a value that is merely a prefix of one entry, or spans two of them, passes the check. Use a list: contains(fromJSON('[\"a\", \"b\"]'), value).", [step_label, job_name]),
		"context": step["if"],
		"discriminator": sprintf("%v:%v:step-if", [job_name, step_index]),
	}
}
