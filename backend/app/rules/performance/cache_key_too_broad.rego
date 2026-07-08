# METADATA
# title: Cache key never misses
# description: Cache key does not include a hash of the lockfile, meaning the cache never invalidates when dependencies change.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/cache@v4
#               with:
#                 path: ~/.npm
#                 key: ${{ runner.os }}-node
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/cache@v4
#               with:
#                 path: ~/.npm
#                 key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
#                 restore-keys: ${{ runner.os }}-node-
#     fix: |
#       Include hashFiles() of your lockfile in the cache key so the cache invalidates when dependencies change.
package greensecops.performance.cache_key_too_broad

import rego.v1

# Detects uses of actions/cache where the cache key does not include hashFiles(),
# which leads to over-broad cache hits and stale dependency caches.

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	contains(step.uses, "actions/cache")
	key := step["with"].key
	is_string(key)
	not contains(key, "hashFiles")
	violation := {
		"rule": "cache_key_too_broad",
		"severity": "medium",
		"category": "performance",
		"job": job_name,
		"step": step.uses,
		"step_index": step_index,
		"message": sprintf("Step in job '%v' uses actions/cache with key '%v' that does not include hashFiles(). Add hashFiles() to invalidate the cache when dependencies change.", [job_name, key]),
		"context": key,
	}
}
