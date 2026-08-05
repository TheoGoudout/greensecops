# METADATA
# title: Memory limit is far above measured peak usage
# description: The container's declared memory limit is many times its observed peak. A limit that far above real usage documents nothing and reserves capacity the workload never uses — on a scheduler that honours reservations, it is capacity denied to everything else.
# custom:
#   severity: low
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       containers: [{"name": "api", "peak_rss_bytes": 90000000, "mem_limit_bytes": 4294967296}]
#     good: |
#       containers: [{"name": "api", "peak_rss_bytes": 380000000, "mem_limit_bytes": 536870912}]
#     fix: |
#       Set the limit from measured peak plus headroom. Leave room for real spikes — this is about a limit set by guesswork, not about trimming to the observed maximum.
package greensecops.container_runtime.reliability.container_memory_limit_mismatch

import rego.v1

_oversize_factor := 8.0

# Below this, the ratio is meaningless: a 4 MB sidecar under a 256 MB limit is
# not over-provisioned in any way worth reporting.
_min_peak_bytes := 16000000

violations contains violation if {
	some container in input.containers
	peak := container.peak_rss_bytes
	limit := container.mem_limit_bytes
	peak > _min_peak_bytes
	limit > 0
	ratio := limit / peak
	ratio > _oversize_factor
	violation := {
		"rule": "container_memory_limit_mismatch",
		"severity": "low",
		"category": "reliability",
		"evidence": sprintf("container '%v' peaked at %v MB under a %v MB limit (%vx)", [container.name, round(peak / 1000000), round(limit / 1000000), round(ratio * 10) / 10]),
		"recommendation": "Set the memory limit from measured peak plus headroom rather than a round guess.",
	}
}
