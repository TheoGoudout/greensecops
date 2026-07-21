# METADATA
# title: Workflow exceeds complexity threshold
# description: Workflow has more than 20 steps across jobs without using reusable workflows or composite actions to reduce complexity.
# custom:
#   severity: info
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         lint:
#           steps: []   # 6 steps
#         test:
#           steps: []   # 8 steps
#         build:
#           steps: []   # 7 steps
#         # total: 21 steps — exceeds threshold
#     good: |
#       # ci.yml — lint + test only
#       jobs:
#         lint:
#           steps: []
#         test:
#           steps: []
#       # release.yml — build + deploy only (separate file)
#     fix: |
#       Split the workflow into smaller, focused workflows (e.g. ci.yml for lint/test, release.yml for build/deploy). Extract repeated job logic into reusable workflows.
package greensecops.maintainability.workflow_too_complex

import rego.v1

# Detects workflows where the total number of steps across all jobs exceeds 20,
# which is a signal that the workflow should be split or refactored.

_total_steps := sum([count(job.steps) | some _, job in input.jobs])

violations contains violation if {
	total := _total_steps
	total > 20
	violation := {
		"rule": "workflow_too_complex",
		"severity": "info",
		"category": "maintainability",
		"job": null,
		"message": sprintf("Workflow has %v total steps across all jobs (threshold: 20). Consider splitting into smaller, focused workflows.", [total]),
		"context": null,
	}
}
