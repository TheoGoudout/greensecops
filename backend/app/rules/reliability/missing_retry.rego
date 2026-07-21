# METADATA
# title: No retry on flaky network step
# description: Steps that download external dependencies or call external APIs have no retry logic, making the pipeline fragile to transient network failures.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - run: npm install
#             - run: curl -fsSL https://example.com/tool | bash
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: nick-fields/retry@7152eba30c6575329ac0576536151aca5a72780e # v3.0.0
#               with:
#                 timeout_minutes: 5
#                 max_attempts: 3
#                 command: npm install
#             - run: curl -fsSL https://example.com/tool | bash
#     fix: |
#       Wrap flaky network steps (curl, npm install, pip install, apt-get) with a retry action such as nick-fields/retry or add shell-level retry loops for critical downloads.
package greensecops.reliability.missing_retry

import rego.v1

# Detects jobs that run network-dependent commands (curl, wget, pip install,
# npm install, apt-get) without any retry action, making them fragile against
# transient network failures.

_network_commands := ["curl", "wget", "pip install", "npm install", "apt-get"]

_has_network_step(steps) if {
	some step in steps
	run := step.run
	some cmd in _network_commands
	contains(run, cmd)
}

_has_retry_action(steps) if {
	some step in steps
	uses := step.uses
	contains(uses, "retry")
}

violations contains violation if {
	some job_name, job in input.jobs
	_has_network_step(job.steps)
	not _has_retry_action(job.steps)
	violation := {
		"rule": "missing_retry",
		"severity": "medium",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Job '%v' runs network-dependent commands (curl/wget/pip/npm/apt-get) without a retry action. Consider adding a retry mechanism for transient failures.", [job_name]),
		"context": null,
	}
}
