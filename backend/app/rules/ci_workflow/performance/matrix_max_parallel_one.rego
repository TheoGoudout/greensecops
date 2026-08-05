# METADATA
# title: Matrix serialised by max-parallel 1
# description: A matrix strategy sets max-parallel to 1, so its combinations run one after another rather than at the same time. The point of a matrix is that its legs are independent, and serialising them turns an N-way matrix into N times the wall-clock without reducing the work done. It is usually a leftover from debugging a flaky leg or from working around a shared resource that has since been fixed.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           strategy:
#             max-parallel: 1
#             matrix:
#               python: ["3.11", "3.12", "3.13"]
#           steps:
#             - run: pytest
#     good: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           strategy:
#             matrix:
#               python: ["3.11", "3.12", "3.13"]
#           steps:
#             - run: pytest
#     fix: |
#       Remove max-parallel and let the legs run together. If they were serialised because they contend over something shared — a fixed database name, a port, a cache key — give each leg its own instead, since that contention will bite again the moment the matrix grows.
package greensecops.ci_workflow.performance.matrix_max_parallel_one

import rego.v1

violations contains violation if {
	some job_name, job in input.jobs
	strategy := job.strategy
	strategy.matrix
	strategy["max-parallel"] == 1

	violation := {
		"rule": "matrix_max_parallel_one",
		"severity": "low",
		"category": "performance",
		"job": job_name,
		"message": sprintf("Job '%v' sets max-parallel: 1, so its matrix legs run one at a time — the same work spread over N times the wall-clock.", [job_name]),
		"context": "max-parallel: 1",
		"discriminator": job_name,
	}
}
