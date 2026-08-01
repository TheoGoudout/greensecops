# METADATA
# title: Container ran with no memory limit
# description: A container was observed doing real work with no memory limit declared. The measured counterpart to compose_missing_resource_limits, which infers the same gap from the Compose file — this one knows how much the workload actually used, so the fix can name a number instead of a guess.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "api", "peak_rss_bytes": 420000000, "mem_limit_bytes": 0}]
#     good: |
#       containers: [{"name": "api", "peak_rss_bytes": 420000000, "mem_limit_bytes": 805306368}]
#     fix: |
#       Set a memory limit from the measured peak plus headroom. Without one the container can consume every byte on the host, and the kernel's OOM killer picks a victim by score rather than by which workload is least important.
package greensecops.container_runtime.energy.container_unbounded_memory

import rego.v1

# Below this the advice is noise: a 4 MB sidecar with no limit is not what
# starves a host, and the limit would be pure ceremony.
_min_peak_bytes := 64000000

violations contains violation if {
	some container in input.containers
	peak := container.peak_rss_bytes
	is_number(peak)
	peak > _min_peak_bytes

	# Exactly 0 — `docker inspect` reports that for "explicitly unlimited".
	# A container the collector could not inspect reports null instead, and
	# must not be read as having declared no limit.
	container.mem_limit_bytes == 0

	violation := {
		"rule": "container_unbounded_memory",
		"severity": "medium",
		"category": "energy",
		"evidence": sprintf("container '%v' peaked at %.0f MB with no memory limit set", [container.name, peak / 1000000]),
		"recommendation": sprintf("Set a memory limit for '%v' — measured peak was %.0f MB, so a limit around %.0f MB leaves headroom.", [container.name, peak / 1000000, (peak * 1.5) / 1000000]),
	}
}
