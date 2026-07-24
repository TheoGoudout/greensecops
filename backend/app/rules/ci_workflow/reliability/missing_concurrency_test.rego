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

test_violation_pr_target_trigger_no_concurrency if {
	violations := missing_concurrency.violations with input as {
		"on": {"pull_request_target": {}},
		"jobs": {"test": {"steps": [{"run": "pytest"}]}},
	}
	count(violations) == 1
}
