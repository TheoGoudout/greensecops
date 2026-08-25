package greensecops.ci_workflow.energy.artifact_reuse_test

import data.greensecops.ci_workflow.energy.artifact_reuse
import rego.v1

_upload(with_block) := {"uses": "actions/upload-artifact@v4", "with": with_block}

_download := {"uses": "actions/download-artifact@v4", "with": {"name": "dist"}}

test_violation_when_nothing_downloads if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"build": {"steps": [_upload({"name": "dist", "path": "dist/"})]},
		"deploy": {"needs": "build", "steps": [{"run": "make dist && ./deploy.sh"}]},
	}}
	count(violations) == 1
	some v in violations
	v.job == "build"
}

test_no_violation_when_a_job_downloads if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"build": {"steps": [_upload({"name": "dist", "path": "dist/"})]},
		"deploy": {"needs": "build", "steps": [_download]},
	}}
	count(violations) == 0
}

# The consumer need not be the job that `needs:` the uploader — this is what
# the previous version reported, and it was not a defect.
test_no_violation_when_an_unrelated_job_downloads if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"build": {"steps": [_upload({"name": "dist", "path": "dist/"})]},
		"deploy": {"needs": "build", "steps": [{"run": "./deploy.sh"}]},
		"publish": {"steps": [_download]},
	}}
	count(violations) == 0
}

test_no_violation_for_a_third_party_downloader if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"build": {"steps": [_upload({"name": "dist", "path": "dist/"})]},
		"deploy": {"steps": [{"uses": "dawidd6/action-download-artifact@v6"}]},
	}}
	count(violations) == 0
}

# Reports, coverage and logs are uploaded to be read by a person.
test_no_violation_for_a_diagnostic_artifact if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"test": {"steps": [_upload({"name": "coverage", "path": "htmlcov/"})]},
	}}
	count(violations) == 0
}

test_no_violation_for_a_report_path if {
	violations := artifact_reuse.violations with input as {"jobs": {
		"test": {"steps": [_upload({"name": "out", "path": "playwright-report/"})]},
	}}
	count(violations) == 0
}

# A reusable workflow hands its artifacts to the caller.
test_no_violation_for_a_reusable_workflow if {
	violations := artifact_reuse.violations with input as {
		"on": {"workflow_call": null},
		"jobs": {"build": {"steps": [_upload({"name": "dist", "path": "dist/"})]}},
	}
	count(violations) == 0
}

test_two_uploads_are_two_findings if {
	violations := artifact_reuse.violations with input as {"jobs": {"build": {"steps": [
		_upload({"name": "dist", "path": "dist/"}),
		_upload({"name": "wheels", "path": "wheels/"}),
	]}}}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
