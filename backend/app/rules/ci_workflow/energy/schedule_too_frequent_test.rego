package greensecops.ci_workflow.energy.schedule_too_frequent_test

import data.greensecops.ci_workflow.energy.schedule_too_frequent
import rego.v1

_schedule(crons) := {"on": {"schedule": [{"cron": c} | some c in crons]}}

test_violation_for_every_five_minutes if {
	violations := schedule_too_frequent.violations with input as _schedule(["*/5 * * * *"])
	count(violations) == 1
	some v in violations
	v.context == "*/5 * * * *"
}

test_violation_for_every_minute if {
	violations := schedule_too_frequent.violations with input as _schedule(["* * * * *"])
	count(violations) == 1
}

test_violation_for_a_quarter_hourly_list if {
	violations := schedule_too_frequent.violations with input as _schedule(["0,15,30,45 * * * *"])
	count(violations) == 1
}

test_no_violation_at_the_threshold if {
	violations := schedule_too_frequent.violations with input as _schedule(["*/30 * * * *"])
	count(violations) == 0
}

test_no_violation_for_a_six_hourly_schedule if {
	violations := schedule_too_frequent.violations with input as _schedule(["0 */6 * * *"])
	count(violations) == 0
}

test_no_violation_for_a_daily_schedule if {
	violations := schedule_too_frequent.violations with input as _schedule(["0 3 * * *"])
	count(violations) == 0
}

# Two entries an hour apart are a twice-daily schedule, not a two-minute one.
test_no_violation_for_two_fixed_daily_times if {
	violations := schedule_too_frequent.violations with input as _schedule(["0 3 * * *", "0 15 * * *"])
	count(violations) == 0
}

test_no_violation_without_a_schedule_trigger if {
	violations := schedule_too_frequent.violations with input as {"on": {"push": {"branches": ["main"]}}}
	count(violations) == 0
}

test_each_frequent_schedule_is_its_own_finding if {
	violations := schedule_too_frequent.violations with input as _schedule(["*/5 * * * *", "*/10 * * * *", "0 3 * * *"])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
