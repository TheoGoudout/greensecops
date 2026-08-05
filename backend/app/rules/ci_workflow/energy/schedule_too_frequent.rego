# METADATA
# title: Scheduled workflow runs very frequently
# description: A cron schedule fires more often than every thirty minutes. A scheduled workflow runs whether or not anything changed, so its cost is paid continuously and forever — a five-minute schedule is close to three hundred runs a day, every day, usually to discover that nothing has happened. Frequent schedules are also the least likely thing in a repository to be revisited, because nothing fails when they are wrong.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       on:
#         schedule:
#           - cron: "*/5 * * * *"
#     good: |
#       on:
#         schedule:
#           - cron: "0 */6 * * *"
#     fix: |
#       Widen the interval to what the workflow is actually for. If it exists to react to something, an event trigger (repository_dispatch, workflow_run, a webhook) does the same job without running when nothing happened.
package greensecops.ci_workflow.energy.schedule_too_frequent

import rego.v1

_min_interval_minutes := 30

# A step value in the minute field: */N. Anything below the threshold fires
# more often than the threshold allows.
_interval_minutes(cron) := interval if {
	minute_field := split(trim_space(cron), " ")[0]
	step := regex.find_n(`^\*/([0-9]+)$`, minute_field, 1)
	count(step) > 0
	interval := to_number(trim_prefix(step[0], "*/"))
}

# An explicit list in the minute field: "0,15,30,45" runs every 15 minutes.
# Approximated by the count, which is exact for the evenly-spaced lists people
# actually write.
_interval_minutes(cron) := interval if {
	minute_field := split(trim_space(cron), " ")[0]
	contains(minute_field, ",")
	interval := 60 / count(split(minute_field, ","))
}

# A bare `*` in the minute field is every minute.
_interval_minutes(cron) := 1 if {
	split(trim_space(cron), " ")[0] == "*"
}

_schedules := input.on.schedule

violations contains violation if {
	some entry in _schedules
	cron := entry.cron
	is_string(cron)
	interval := _interval_minutes(cron)
	interval < _min_interval_minutes

	violation := {
		"rule": "schedule_too_frequent",
		"severity": "medium",
		"category": "energy",
		"message": sprintf("The schedule '%v' fires about every %v minutes, so the workflow runs continuously whether or not anything changed. Widen the interval, or use an event trigger.", [cron, round(interval)]),
		"context": cron,
		"discriminator": cron,
	}
}
