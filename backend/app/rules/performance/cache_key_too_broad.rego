package greensecops.performance.cache_key_too_broad

import rego.v1

# Detects uses of actions/cache where the cache key does not include hashFiles(),
# which leads to over-broad cache hits and stale dependency caches.

violations contains violation if {
    some job_name, job in input.jobs
    some step in job.steps
    contains(step.uses, "actions/cache")
    key := step["with"].key
    is_string(key)
    not contains(key, "hashFiles")
    violation := {
        "rule": "cache_key_too_broad",
        "severity": "medium",
        "category": "performance",
        "job": job_name,
        "message": sprintf("Step in job '%v' uses actions/cache with key '%v' that does not include hashFiles(). Add hashFiles() to invalidate the cache when dependencies change.", [job_name, key]),
        "context": key,
    }
}
