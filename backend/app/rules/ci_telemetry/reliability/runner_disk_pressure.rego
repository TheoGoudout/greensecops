# METADATA
# title: Runner ran low on free disk space
# description: The runner's declared free disk space at job start was below 2 GB, a common cause of intermittent "no space left on device" failures in build/test steps that write large artifacts, caches, or containers.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       runner_specs: {"disk_free_gb": 1.2}
#     good: |
#       runner_specs: {"disk_free_gb": 18.5}
#     fix: |
#       Clean up unused caches/artifacts earlier in the job, or move to a runner with more disk.
package greensecops.ci_telemetry.reliability.runner_disk_pressure

import rego.v1

_low_disk_gb_threshold := 2.0

violations contains violation if {
	disk_free_gb := input.runner_specs.disk_free_gb
	disk_free_gb < _low_disk_gb_threshold
	violation := {
		"rule": "runner_disk_pressure",
		"severity": "medium",
		"category": "reliability",
		"evidence": sprintf("disk_free_gb=%v", [round(disk_free_gb * 10) / 10]),
		"recommendation": "Free up disk earlier in the job (prune caches/artifacts), or move to a runner with more disk.",
	}
}
