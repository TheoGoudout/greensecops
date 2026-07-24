# METADATA
# title: Workflow exceeds complexity threshold
# description: Workflow has more than 20 steps across jobs without using reusable workflows or composite actions to reduce complexity.
# custom:
#   severity: info
#   detection: heuristic
#   examples:
#     bad: |
#       # One monolithic job with 21 steps (threshold is 20).
#       jobs:
#         everything:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm ci
#             - run: npm run lint
#             - run: npm run typecheck
#             - run: npm run build
#             - run: npm test
#             - run: npm run test:integration
#             - run: npm run test:e2e
#             - run: npm run bundle
#             - run: ./scripts/build-image.sh
#             - run: ./scripts/scan-image.sh
#             - run: ./scripts/push-image.sh
#             - run: ./scripts/deploy-staging.sh
#             - run: ./scripts/smoke-test.sh
#             - run: ./scripts/deploy-prod.sh
#             - run: ./scripts/healthcheck.sh
#             - run: ./scripts/purge-cache.sh
#             - run: ./scripts/tag-release.sh
#             - run: ./scripts/changelog.sh
#             - run: ./scripts/publish-docs.sh
#             - run: ./scripts/notify-slack.sh
#             - run: ./scripts/cleanup.sh
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
package greensecops.ci_workflow.maintainability.workflow_too_complex

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
