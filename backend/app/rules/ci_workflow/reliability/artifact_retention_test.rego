package greensecops.ci_workflow.reliability.artifact_retention_test

import data.greensecops.ci_workflow.reliability.artifact_retention
import rego.v1

test_violation_upload_without_retention if {
	violations := artifact_retention.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/upload-artifact@v4",
						"with": {"name": "dist", "path": "./dist"},
					},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "artifact_retention"
}

test_no_violation_upload_with_retention if {
	violations := artifact_retention.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/upload-artifact@v4",
						"with": {"name": "dist", "path": "./dist", "retention-days": 7},
					},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_no_upload_step if {
	violations := artifact_retention.violations with input as {"jobs": {"build": {"steps": [{"uses": "actions/checkout@v4"}]}}}
	count(violations) == 0
}
