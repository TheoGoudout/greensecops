package greensecops.ci_telemetry.energy.long_running_job_test

import data.greensecops.ci_telemetry.energy.long_running_job
import rego.v1

# Input is the {"runner_specs", "metrics"} pair the TelemetryRun row stores.
# `duration_ms` is set by the Action's post step only, so a run ingested at the
# pre-step phase has no duration at all.

_metrics(metrics) := {"runner_specs": {"vcpus": 4}, "metrics": metrics}

test_violation_on_a_long_run if {
	violations := long_running_job.violations with input as _metrics({"duration_ms": 4200000})
	count(violations) == 1
	some v in violations
	v.category == "energy"
	contains(v.evidence, "70 minutes")
}

test_no_violation_at_the_threshold if {
	violations := long_running_job.violations with input as _metrics({"duration_ms": 2700000})
	count(violations) == 0
}

test_no_violation_on_a_short_run if {
	violations := long_running_job.violations with input as _metrics({"duration_ms": 480000})
	count(violations) == 0
}

test_no_violation_before_the_post_step_sets_a_duration if {
	violations := long_running_job.violations with input as _metrics({"cpu_load_percent": 40})
	count(violations) == 0
}

test_no_violation_when_duration_is_null if {
	violations := long_running_job.violations with input as _metrics({"duration_ms": null})
	count(violations) == 0
}

# A whole number of minutes is an integer after the division, which sprintf's
# %f would have rejected — see the dynamic-findings formatting fix.
test_evidence_is_readable_for_a_whole_number_of_minutes if {
	violations := long_running_job.violations with input as _metrics({"duration_ms": 3600000})
	some v in violations
	v.evidence == "the run took 60 minutes"
}
