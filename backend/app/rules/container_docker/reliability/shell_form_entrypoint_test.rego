package greensecops.container_docker.reliability.shell_form_entrypoint_test

import data.greensecops.container_docker.reliability.shell_form_entrypoint
import rego.v1

# Only the final stage ships, and only the *last* CMD/ENTRYPOINT in it takes
# effect — an earlier one a later instruction overrides never runs.

_stage(index, final) := {
	"index": index,
	"name": null,
	"is_final": final,
	"__start_line__": 1,
	"__end_line__": 9,
}

_df(stages, instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": instructions,
}]}

_inst(keyword, value, stage) := {
	"instruction": keyword,
	"value": value,
	"flags": {},
	"stage": stage,
	"heredoc": null,
	"__start_line__": 7,
	"__end_line__": 7,
}

test_violation_for_shell_form_cmd if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, true)],
		[_inst("CMD", "node /app/server.js", 0)],
	)
	count(violations) == 1
	some v in violations
	v.discriminator == "CMD"
}

test_violation_for_shell_form_entrypoint if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, true)],
		[_inst("ENTRYPOINT", "/usr/local/bin/start.sh", 0)],
	)
	count(violations) == 1
	some v in violations
	v.discriminator == "ENTRYPOINT"
}

test_no_violation_for_exec_form if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, true)],
		[_inst("CMD", "[\"node\", \"/app/server.js\"]", 0)],
	)
	count(violations) == 0
}

test_no_violation_when_neither_is_declared if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, true)],
		[_inst("RUN", "npm ci", 0)],
	)
	count(violations) == 0
}

# A builder stage's CMD never ships.
test_no_violation_for_a_non_final_stage if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, false), _stage(1, true)],
		[
			_inst("CMD", "npm run build", 0),
			_inst("CMD", "[\"node\", \"server.js\"]", 1),
		],
	)
	count(violations) == 0
}

# Only the last CMD takes effect, so a shell-form one that is overridden by an
# exec-form one is not a finding.
test_no_violation_when_a_later_exec_form_overrides if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, true)],
		[
			_inst("CMD", "node old.js", 0),
			_inst("CMD", "[\"node\", \"server.js\"]", 0),
		],
	)
	count(violations) == 0
}

test_violation_when_a_later_shell_form_overrides_an_exec_form if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, true)],
		[
			_inst("CMD", "[\"node\", \"server.js\"]", 0),
			_inst("CMD", "node other.js", 0),
		],
	)
	count(violations) == 1
}

test_entrypoint_and_cmd_are_separate_findings if {
	violations := shell_form_entrypoint.violations with input as _df(
		[_stage(0, true)],
		[
			_inst("ENTRYPOINT", "/start.sh", 0),
			_inst("CMD", "--port 8080", 0),
		],
	)
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
