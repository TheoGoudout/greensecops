package greensecops.ci_workflow.maintainability.missing_workflow_description_test

import data.greensecops.ci_workflow.maintainability.missing_workflow_description as missing_name
import rego.v1

_named_job := {"name": "Build the app", "runs-on": "ubuntu-latest", "steps": []}

test_violation_when_the_workflow_has_no_name if {
	violations := missing_name.violations with input as {"jobs": {"build": _named_job}}
	count(violations) == 1
	some v in violations
	v.job == null
	v.discriminator == "workflow"
}

test_no_violation_when_the_workflow_is_named if {
	violations := missing_name.violations with input as {"name": "CI", "jobs": {"build": _named_job}}
	count(violations) == 0
}

# An unnamed job is not a finding: GitHub falls back to the job key, which is
# the name people write `needs:` against. Reporting it produced one `info`
# finding per job on most workflows in existence.
test_no_violation_when_a_job_has_no_name if {
	violations := missing_name.violations with input as {
		"name": "CI",
		"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": []}},
	}
	count(violations) == 0
}

test_only_one_finding_per_workflow if {
	violations := missing_name.violations with input as {"jobs": {
		"build": {"steps": []},
		"test": {"steps": []},
	}}
	count(violations) == 1
}

test_severity_is_informational if {
	violations := missing_name.violations with input as {"jobs": {"build": _named_job}}
	some v in violations
	v.severity == "info"
	v.category == "maintainability"
}
