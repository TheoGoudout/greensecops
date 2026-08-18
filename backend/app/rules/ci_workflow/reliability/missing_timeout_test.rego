package greensecops.ci_workflow.reliability.missing_timeout_test

import data.greensecops.ci_workflow.reliability.missing_timeout
import rego.v1

test_violation_when_no_timeout if {
	violations := missing_timeout.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest",
				"steps": [{"uses": "actions/checkout@v4"}],
			},
		},
	}
	count(violations) == 1
}

test_no_violation_when_timeout_set if {
	violations := missing_timeout.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest",
				"timeout-minutes": 30,
				"steps": [{"uses": "actions/checkout@v4"}],
			},
		},
	}
	count(violations) == 0
}

# GitHub rejects `timeout-minutes` on a job that calls a reusable workflow, so
# reporting one was an unfixable finding — and the generated fix wrote a key that
# makes the workflow invalid. The timeout belongs on the jobs inside the called
# workflow, where this rule finds it on its own.
test_no_violation_for_reusable_workflow_call if {
	violations := missing_timeout.violations with input as {"jobs": {"deploy": {
		"uses": "./.github/workflows/deploy-reusable.yml",
		"with": {"environment": "staging"},
	}}}
	count(violations) == 0
}

test_violation_still_reported_for_ordinary_jobs_alongside_a_reusable_call if {
	violations := missing_timeout.violations with input as {"jobs": {
		"call": {"uses": "./.github/workflows/deploy-reusable.yml"},
		"lint": {"runs-on": "ubuntu-latest", "steps": []},
	}}
	count(violations) == 1
	some v in violations
	v.job == "lint"
}

test_violation_only_for_jobs_without_timeout if {
	violations := missing_timeout.violations with input as {
		"jobs": {
			"build": {
				"runs-on": "ubuntu-latest",
				"timeout-minutes": 30,
				"steps": [],
			},
			"deploy": {
				"runs-on": "ubuntu-latest",
				"steps": [],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
}
