# METADATA
# title: Missing job timeout
# description: Job has no timeout-minutes set. Without a timeout, a hung job will consume runner minutes until the 6-hour GitHub default limit, blocking other workflows.
# custom:
#   severity: high
#   severity_weight: 1.5
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm test
#     good: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           timeout-minutes: 15
#           steps:
#             - run: npm test
#     fix: |
#       Add timeout-minutes to every job. Set a value slightly above the expected maximum duration (e.g. 15 minutes for a test suite that normally runs in 5 minutes).
package greensecops.ci_workflow.reliability.missing_timeout

import data.greensecops.lib.workflow as wf
import rego.v1

violations contains violation if {
	some job_name, job in input.jobs
	not job["timeout-minutes"]

	# A job that calls a reusable workflow cannot carry `timeout-minutes` —
	# GitHub rejects it, along with most other job-level keys, when `uses:` is
	# present. The timeout belongs on the jobs inside the called workflow, where
	# this rule will find it. Reporting the caller produced an unfixable
	# finding, and the generated fix wrote a key that makes the workflow
	# invalid.
	not wf.is_reusable_call(job)

	violation := {
		"rule": "missing_timeout",
		"severity": "high",
		"category": "reliability",
		"job": job_name,
		"message": sprintf("Job '%v' has no timeout-minutes configured. Without a timeout a hung job runs for up to 6 hours.", [job_name]),
		"context": null,
	}
}
