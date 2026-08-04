package greensecops.ci_telemetry.energy.excessive_network_transfer_test

import data.greensecops.ci_telemetry.energy.excessive_network_transfer as excessive_transfer
import rego.v1

_metrics(metrics) := {"runner_specs": {"vcpus": 4}, "metrics": metrics}

test_violation_when_the_total_is_large if {
	violations := excessive_transfer.violations with input as _metrics({
		"net_bytes_recv": 9000000000,
		"net_bytes_sent": 200000000,
	})
	count(violations) == 1
}

# The threshold is on the sum, so neither direction alone has to clear it.
test_violation_when_only_the_sum_clears_the_threshold if {
	violations := excessive_transfer.violations with input as _metrics({
		"net_bytes_recv": 3000000000,
		"net_bytes_sent": 3000000000,
	})
	count(violations) == 1
}

test_no_violation_at_the_threshold if {
	violations := excessive_transfer.violations with input as _metrics({
		"net_bytes_recv": 5000000000,
		"net_bytes_sent": 0,
	})
	count(violations) == 0
}

test_no_violation_for_a_well_cached_run if {
	violations := excessive_transfer.violations with input as _metrics({
		"net_bytes_recv": 700000000,
		"net_bytes_sent": 90000000,
	})
	count(violations) == 0
}

# Both counters are optional on the metrics payload.
test_no_violation_when_counters_are_absent if {
	violations := excessive_transfer.violations with input as _metrics({"cpu_load_percent": 40})
	count(violations) == 0
}

test_no_violation_when_a_counter_is_null if {
	violations := excessive_transfer.violations with input as _metrics({
		"net_bytes_recv": null,
		"net_bytes_sent": 6000000000,
	})
	count(violations) == 0
}

test_counts_a_single_direction_when_the_other_is_missing if {
	violations := excessive_transfer.violations with input as _metrics({"net_bytes_recv": 9000000000})
	count(violations) == 1
	some v in violations
	v.evidence == "the run transferred 9000 MB over the network"
}
