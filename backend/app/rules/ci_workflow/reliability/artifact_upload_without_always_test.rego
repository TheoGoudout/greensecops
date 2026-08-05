package greensecops.ci_workflow.reliability.artifact_upload_without_always_test

import data.greensecops.ci_workflow.reliability.artifact_upload_without_always as no_always
import rego.v1

_workflow(steps) := {"jobs": {"test": {
	"runs-on": "ubuntu-latest",
	"steps": steps,
	"__start_line__": 4,
	"__end_line__": 20,
}}}

_upload(with_block, condition) := object.union(
	{
		"uses": "actions/upload-artifact@v4",
		"with": with_block,
		"__start_line__": 10,
		"__end_line__": 14,
	},
	condition,
)

test_violation_for_an_unconditional_report_upload if {
	violations := no_always.violations with input as _workflow([_upload({"name": "test-report", "path": "report.xml"}, {})])
	count(violations) == 1
	some v in violations
	v.job == "test"
	v.step_index == 0
}

test_no_violation_when_the_step_runs_always if {
	violations := no_always.violations with input as _workflow([_upload(
		{"name": "test-report", "path": "report.xml"},
		{"if": "always()"},
	)])
	count(violations) == 0
}

test_no_violation_when_the_step_runs_on_failure if {
	violations := no_always.violations with input as _workflow([_upload(
		{"name": "screenshots", "path": "shots/"},
		{"if": "failure()"},
	)])
	count(violations) == 0
}

# A build output is meant to exist only on success, so the default condition is
# correct for it — this rule is about evidence, not artefacts.
test_no_violation_for_a_build_output if {
	violations := no_always.violations with input as _workflow([_upload(
		{"name": "dist", "path": "dist/"},
		{},
	)])
	count(violations) == 0
}

test_the_path_alone_is_enough_to_identify_a_diagnostic if {
	violations := no_always.violations with input as _workflow([_upload(
		{"name": "output", "path": "pytest-coverage.xml"},
		{},
	)])
	count(violations) == 1
}

test_no_violation_for_a_step_that_uploads_nothing if {
	violations := no_always.violations with input as _workflow([{"run": "pytest"}])
	count(violations) == 0
}

test_the_finding_carries_the_step_line_span if {
	violations := no_always.violations with input as _workflow([_upload({"name": "junit-report"}, {})])
	some v in violations
	v.line_start == 10
	v.line_end == 14
}

test_each_upload_is_its_own_finding if {
	violations := no_always.violations with input as _workflow([
		_upload({"name": "test-report"}, {}),
		{"run": "pytest"},
		_upload({"name": "coverage"}, {}),
		_upload({"name": "dist"}, {}),
	])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
