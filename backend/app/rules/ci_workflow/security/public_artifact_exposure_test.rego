package greensecops.ci_workflow.security.public_artifact_exposure_test

import data.greensecops.ci_workflow.security.public_artifact_exposure
import rego.v1

test_violation_upload_without_retention if {
	violations := public_artifact_exposure.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/upload-artifact@v4",
						"with": {
							"name": "dist",
							"path": "dist/",
						},
					},
				],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.rule == "public_artifact_exposure"
	v.job == "build"
}

test_no_violation_upload_with_retention if {
	violations := public_artifact_exposure.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/upload-artifact@v4",
						"with": {
							"name": "dist",
							"path": "dist/",
							"retention-days": 7,
						},
					},
				],
			},
		},
	}
	count(violations) == 0
}

test_no_violation_no_upload_step if {
	violations := public_artifact_exposure.violations with input as {"jobs": {"build": {"steps": [{"uses": "actions/checkout@v4"}]}}}
	count(violations) == 0
}

test_violation_multiple_jobs_without_retention if {
	violations := public_artifact_exposure.violations with input as {
		"jobs": {
			"build": {
				"steps": [
					{
						"uses": "actions/upload-artifact@v4",
						"with": {"name": "build", "path": "build/"},
					},
				],
			},
			"test": {
				"steps": [
					{
						"uses": "actions/upload-artifact@v3",
						"with": {"name": "coverage", "path": "coverage/"},
					},
				],
			},
		},
	}
	count(violations) == 2
}
