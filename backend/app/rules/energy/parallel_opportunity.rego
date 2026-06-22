# METADATA
# title: Sequential jobs without dependency
# description: Multiple jobs run sequentially but have no dependency on each other. Running them in parallel would reduce total pipeline duration and energy use.
# custom:
#   severity: low
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         lint:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run lint
#         test:
#           needs: lint
#           steps:
#             - run: npm test
#         build:
#           needs: test
#           steps:
#             - run: npm run build
#     good: |
#       jobs:
#         lint:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run lint
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm test
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run build
#     fix: |
#       Remove unnecessary needs: dependencies between jobs that do not share outputs. GitHub Actions runs independent jobs in parallel by default.
package greensecops.energy.parallel_opportunity

import rego.v1

# Detects when 3 or more jobs all lack a 'needs:' key, meaning they could
# already run in parallel but the intent is unclear and sequential execution
# may be assumed. Flags to confirm parallelism is being used intentionally.

_jobs_without_needs := {job_name |
	some job_name, job in input.jobs
	not job.needs
}

violations contains violation if {
	independent := _jobs_without_needs
	count(independent) >= 3
	violation := {
		"rule": "parallel_opportunity",
		"severity": "low",
		"category": "energy",
		"job": null,
		"message": sprintf("%v jobs have no 'needs:' key and will run in parallel. Verify this is intentional and that runner concurrency is not constrained.", [count(independent)]),
		"context": null,
	}
}
