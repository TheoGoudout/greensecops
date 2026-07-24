# METADATA
# title: Runner ran under high memory pressure
# description: Telemetry from a completed workflow run shows RAM usage above 90% at collection time, which risks the OS OOM-killer terminating a build step or test process non-deterministically.
# custom:
#   severity: high
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       metrics: {"ram_percent": 96.5}
#     good: |
#       metrics: {"ram_percent": 58.0}
#     fix: |
#       Move to a runner with more RAM, or reduce the job's memory footprint (streaming instead of buffering, smaller build parallelism, disabling unnecessary caches).
package greensecops.ci_telemetry.reliability.high_memory_pressure

import rego.v1

_high_ram_threshold := 90.0

violations contains violation if {
	ram_percent := input.metrics.ram_percent
	ram_percent > _high_ram_threshold
	violation := {
		"rule": "high_memory_pressure",
		"severity": "high",
		"category": "reliability",
		"evidence": sprintf("RAM=%.1f%%", [ram_percent]),
		"recommendation": "Move to a larger runner or reduce the job's memory footprint — usage came close to exhausting available RAM.",
	}
}
