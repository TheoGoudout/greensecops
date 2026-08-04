# METADATA
# title: Workflow run took a long time
# description: Measured wall-clock duration shows the run occupied a runner for a long stretch. Duration is the one CI cost that is paid in full every time regardless of what the job found — a long run holds a machine, delays every job queued behind it, and is charged by the minute. It is also the signal most likely to drift upward unnoticed, because no individual commit makes it worse by much.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       metrics: {"duration_ms": 4200000}
#     good: |
#       metrics: {"duration_ms": 480000}
#     fix: |
#       Split the workflow so independent work runs in parallel jobs rather than sequentially, and cache whatever is rebuilt from scratch each run. If one step dominates, check whether it can run only on the paths it depends on instead of on every push.
package greensecops.ci_telemetry.energy.long_running_job

import rego.v1

# 45 minutes. A build that takes this long has stopped being something a
# contributor waits for.
_long_run_ms := 2700000

violations contains violation if {
	duration := object.get(input.metrics, "duration_ms", 0)

	# Only the post step sets duration_ms; a run reported at the pre-step phase
	# has no duration yet.
	is_number(duration)
	duration > _long_run_ms

	violation := {
		"rule": "long_running_job",
		"severity": "medium",
		"category": "energy",
		"evidence": sprintf("the run took %v minutes", [round(duration / 60000)]),
		"recommendation": "Split independent work into parallel jobs and cache what is rebuilt every run. A run this long holds a machine and delays everything queued behind it.",
	}
}
