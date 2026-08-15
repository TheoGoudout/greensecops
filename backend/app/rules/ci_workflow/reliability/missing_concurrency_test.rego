package greensecops.ci_workflow.reliability.missing_concurrency_test

import data.greensecops.ci_workflow.reliability.missing_concurrency
import rego.v1

test_violation_pr_trigger_no_concurrency if {
	violations := missing_concurrency.violations with input as {
		"on": {"pull_request": {"branches": ["main"]}},
		"jobs": {"test": {"steps": [{"run": "pytest"}]}},
	}
	count(violations) == 1
	some v in violations
	v.rule == "missing_concurrency"
}

test_no_violation_pr_trigger_with_concurrency if {
	violations := missing_concurrency.violations with input as {
		"on": {"pull_request": {"branches": ["main"]}},
		"concurrency": {"group": "pr-${{ github.ref }}", "cancel-in-progress": true},
		"jobs": {"test": {"steps": [{"run": "pytest"}]}},
	}
	count(violations) == 0
}

test_no_violation_push_trigger_no_concurrency if {
	violations := missing_concurrency.violations with input as {
		"on": {"push": {"branches": ["main"]}},
		"jobs": {"deploy": {"steps": [{"run": "make deploy"}]}},
	}
	count(violations) == 0
}

# The list form has always been handled by the rule but was never tested; it is
# now handled by the shared trigger_names helper.
test_violation_pr_trigger_list_form if {
	violations := missing_concurrency.violations with input as {
		"on": ["push", "pull_request"],
		"jobs": {"test": {"steps": [{"run": "pytest"}]}},
	}
	count(violations) == 1
}

# Per-job concurrency is a valid way to express this, and sometimes the only
# one — a cancellable test job beside a must-not-be-cancelled publish job cannot
# be described at the top level.
test_no_violation_when_every_job_limits_concurrency if {
	violations := missing_concurrency.violations with input as {
		"on": {"pull_request": {}},
		"jobs": {
			"test": {"concurrency": {"group": "test-${{ github.ref }}", "cancel-in-progress": true}, "steps": []},
			"publish": {"concurrency": {"group": "publish", "cancel-in-progress": false}, "steps": []},
		},
	}
	count(violations) == 0
}

test_violation_when_only_some_jobs_limit_concurrency if {
	violations := missing_concurrency.violations with input as {
		"on": {"pull_request": {}},
		"jobs": {
			"test": {"concurrency": {"group": "test"}, "steps": []},
			"lint": {"steps": []},
		},
	}
	count(violations) == 1
}

test_violation_pr_target_trigger_no_concurrency if {
	violations := missing_concurrency.violations with input as {
		"on": {"pull_request_target": {}},
		"jobs": {"test": {"steps": [{"run": "pytest"}]}},
	}
	count(violations) == 1
}
