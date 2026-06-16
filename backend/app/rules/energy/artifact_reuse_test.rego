package greensecops.energy.artifact_reuse_test

import data.greensecops.energy.artifact_reuse
import rego.v1

test_violation_downstream_does_not_download if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"build": {"steps": [{"uses": "actions/upload-artifact@v4", "with": {"name": "dist"}}]},
		"deploy": {
			"needs": ["build"],
			"steps": [{"run": "echo deploy"}],
		},
	}}
	count(violations) == 1
	some v in violations
	v.rule == "artifact_reuse"
	v.job == "deploy"
}

test_no_violation_downstream_downloads if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"build": {"steps": [{"uses": "actions/upload-artifact@v4", "with": {"name": "dist"}}]},
		"deploy": {
			"needs": ["build"],
			"steps": [{"uses": "actions/download-artifact@v4", "with": {"name": "dist"}}],
		},
	}}
	count(violations) == 0
}

test_no_violation_no_upload if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"build": {"steps": [{"run": "make build"}]},
		"deploy": {
			"needs": ["build"],
			"steps": [{"run": "echo deploy"}],
		},
	}}
	count(violations) == 0
}
