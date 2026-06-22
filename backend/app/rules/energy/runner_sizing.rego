# METADATA
# title: Oversized runner for job complexity
# description: Job uses a large runner (8+ vCPUs) but contains only lightweight steps like linting or unit tests. Downsize to a standard runner to reduce cost and carbon footprint.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest-8-cores
#           steps:
#             - uses: actions/checkout@v4
#             - run: npm test
#     good: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v4
#             - run: npm test
#     fix: |
#       Downsize the runner to ubuntu-latest or a 2-core equivalent. Reserve large runners for compilation, model training, or other parallelizable compute tasks.
package greensecops.energy.runner_sizing

import rego.v1

# Detects jobs that request large/expensive runners but have 3 or fewer steps,
# suggesting the heavy runner is not justified by the workload.

_large_runner(runner) if {
	some label in ["large", "xlarge", "2xlarge", "8-core", "16-core", "ubuntu-latest-8"]
	contains(runner, label)
}

violations contains violation if {
	some job_name, job in input.jobs
	runner := job["runs-on"]
	is_string(runner)
	_large_runner(runner)
	count(job.steps) <= 3
	violation := {
		"rule": "runner_sizing",
		"severity": "medium",
		"category": "energy",
		"job": job_name,
		"message": sprintf("Job '%v' uses a large runner ('%v') but has only %v step(s). Downsize the runner to reduce energy consumption.", [job_name, runner, count(job.steps)]),
		"context": runner,
	}
}
