package greensecops.ci_workflow.maintainability.deprecated_workflow_commands_test

import data.greensecops.ci_workflow.maintainability.deprecated_workflow_commands as deprecated_commands
import rego.v1

_job(steps) := {"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": steps}}}

test_violation_for_set_output if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo \"::set-output name=version::1.2.3\""}])
	count(violations) == 1
	some v in violations
	v.context == "set-output"
	contains(v.message, "$GITHUB_OUTPUT")
}

test_violation_for_set_env if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo \"::set-env name=FOO::bar\""}])
	count(violations) == 1
	some v in violations
	contains(v.message, "$GITHUB_ENV")
}

test_violation_for_add_path if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo \"::add-path::/usr/local/bin\""}])
	count(violations) == 1
}

test_violation_for_save_state if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo \"::save-state name=pid::$PID\""}])
	count(violations) == 1
}

# The replacement writes through a file rather than stdout.
test_no_violation_for_the_github_output_file if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo \"version=1.2.3\" >> \"$GITHUB_OUTPUT\""}])
	count(violations) == 0
}

# Commands that were never removed stay valid.
test_no_violation_for_a_supported_workflow_command if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo \"::error file=app.js,line=1::Something failed\""}])
	count(violations) == 0
}

test_no_violation_for_the_group_command if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo '::group::Build output'"}])
	count(violations) == 0
}

test_no_violation_for_a_plain_script if {
	violations := deprecated_commands.violations with input as _job([{"run": "make build"}])
	count(violations) == 0
}

test_each_removed_command_is_its_own_finding if {
	violations := deprecated_commands.violations with input as _job([{"run": "echo \"::set-output name=a::1\"\necho \"::set-env name=B::2\"\n"}])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
