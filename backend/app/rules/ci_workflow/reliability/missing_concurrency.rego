# METADATA
# title: Missing concurrency group on PR workflow
# description: PR-triggered workflow has no concurrency group. Multiple pushes to the same PR will queue redundant runs instead of cancelling the previous one.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       on:
#         pull_request:
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm test
#     good: |
#       on:
#         pull_request:
#       concurrency:
#         group: ${{ github.workflow }}-${{ github.ref }}
#         cancel-in-progress: true
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm test
#     fix: |
#       Add a top-level concurrency block with a group key that includes github.ref and set cancel-in-progress: true to cancel superseded runs automatically.
package greensecops.ci_workflow.reliability.missing_concurrency

import data.greensecops.lib.workflow as wf
import rego.v1

# Detects workflows triggered by pull_request or pull_request_target that do
# not define a concurrency group, which can lead to redundant concurrent runs
# for the same PR.

_has_pr_trigger if {
	some trigger in ["pull_request", "pull_request_target"]
	wf.has_trigger(trigger)
}

# Concurrency scoped per job is a valid way to express this, and often the right
# one — a workflow that fans out to a cancellable test job and a
# must-not-be-cancelled publish job cannot say that at the top level. Requiring
# the top-level key regardless reported workflows that already handled it.
_every_job_limits_concurrency if {
	count(input.jobs) > 0
	every _, job in input.jobs {
		job.concurrency
	}
}

violations contains violation if {
	_has_pr_trigger
	not input.concurrency
	not _every_job_limits_concurrency
	violation := {
		"rule": "missing_concurrency",
		"severity": "medium",
		"category": "reliability",
		"job": null,
		"message": "Workflow triggers on pull_request/pull_request_target with no concurrency group, at the top level or on every job. Each push to a branch starts another full run while the previous one is still going. Add a concurrency group keyed on the pull request so superseded runs are cancelled.",
		"context": null,
	}
}
