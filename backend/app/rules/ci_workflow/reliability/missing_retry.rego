# METADATA
# title: No retry on flaky network step
# description: "A step fetches a file with curl or wget and no retry, so a transient DNS or connection failure fails the whole run. Package managers are out of scope — npm, pip and apt-get already retry internally, so wrapping them adds nothing. Detection ignores shell comments and recognises the retry mechanisms that already exist: curl's own --retry, wget's --tries, a retry action, or a hand-rolled loop."
# custom:
#   severity: low
#   severity_weight: 0.6
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - run: curl -fsSL -o tool https://example.com/tool
#     good: |
#       jobs:
#         build:
#           steps:
#             - run: curl -fsSL --retry 3 --retry-connrefused -o tool https://example.com/tool
#     fix: |
#       Add the downloader's own retry flag — curl --retry 3 --retry-connrefused, wget --tries=3 — or wrap the step in a retry action. A hand-rolled loop works too, but make sure it still fails the step when every attempt fails; `for i in 1 2 3; do cmd && break; sleep 5; done` exits 0 whether or not the command ever succeeded.
package greensecops.ci_workflow.reliability.missing_retry

import rego.v1

# Shell comments are not commands. The previous version tested the raw `run:`
# block with `contains()`, so `# curl the API later` and `echo "run curl ..."`
# both counted as network steps.
_code(run) := regex.replace(run, `#[^\n]*`, "")

# Only raw downloaders. Package managers are deliberately absent: npm, pip,
# apt-get, cargo and go all retry internally by default (npm's fetch-retries is
# 2, pip's --retries is 5), so demanding a retry wrapper around `npm ci` asks
# the author to duplicate something the tool already does. What does not retry
# unless told to is a bare `curl` or `wget` pulling an installer, which is the
# case worth reporting and the case with a one-flag fix.
#
# Word-boundary matched, so `apt-get-wrapper.sh` is not `apt-get`.
_network_patterns := [
	`\bcurl\b`,
	`\bwget\b`,
]

_is_network_step(step) if {
	run := step.run
	is_string(run)
	some pattern in _network_patterns
	regex.match(pattern, _code(run))
}

# Retry mechanisms already present, in any of the forms people actually write.
_retry_patterns := [
	`--retry[\s=]`,
	`--retry-connrefused`,
	`--retry-all-errors`,
	`--tries[\s=]`,
	`\buntil\s`,
	`\bfor\s+\w+\s+in\b[\s\S]*\bdo\b`,
	`\bwhile\s`,
]

_step_has_retry(step) if {
	run := step.run
	is_string(run)
	some pattern in _retry_patterns
	regex.match(pattern, _code(run))
}

_job_has_retry_action(steps) if {
	some step in steps
	contains(step.uses, "retry")
}

violations contains violation if {
	some job_name, job in input.jobs
	not _job_has_retry_action(job.steps)

	some step_index, step in job.steps
	_is_network_step(step)
	not _step_has_retry(step)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "missing_retry",
		"severity": "low",
		"category": "reliability",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' downloads from the network with no retry. A transient failure fails the run. Add the downloader's own retry flag, or wrap the step in a retry action.", [step_label, job_name]),
		"context": null,
	}
}
