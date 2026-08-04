package greensecops.ci_workflow.maintainability.missing_workflow_description_test

import data.greensecops.ci_workflow.maintainability.missing_workflow_description as missing_name
import rego.v1

# Two independent clauses: the workflow's own `name`, and each job's. The
# workflow-level finding reports job: null, which is what distinguishes the two
# in the finding list.

_named_job := {"name": "Build the app", "runs-on": "ubuntu-latest", "steps": []}

test_violation_when_the_workflow_has_no_name if {
	violations := missing_name.violations with input as {"jobs": {"build": _named_job}}
	count(violations) == 1
	some v in violations
	v.job == null
}

test_violation_when_a_job_has_no_name if {
	violations := missing_name.violations with input as {
		"name": "CI",
		"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": []}},
	}
	count(violations) == 1
	some v in violations
	v.job == "build"
}

test_no_violation_when_everything_is_named if {
	violations := missing_name.violations with input as {"name": "CI", "jobs": {"build": _named_job}}
	count(violations) == 0
}

test_workflow_and_job_findings_are_independent if {
	violations := missing_name.violations with input as {"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": []}}}
	count(violations) == 2
	{v.job | some v in violations} == {null, "build"}
}

test_each_unnamed_job_is_its_own_finding if {
	violations := missing_name.violations with input as {
		"name": "CI",
		"jobs": {
			"build": {"steps": []},
			"test": {"steps": []},
			"lint": _named_job,
		},
	}
	count(violations) == 2
	{v.job | some v in violations} == {"build", "test"}
}

test_severity_is_informational if {
	violations := missing_name.violations with input as {"jobs": {"build": _named_job}}
	some v in violations
	v.severity == "info"
	v.category == "maintainability"
}
