package greensecops.container_docker.reliability.missing_cmd_or_entrypoint_test

import data.greensecops.container_docker.reliability.missing_cmd_or_entrypoint as missing_command
import rego.v1

_stage(index, name, final) := {
	"index": index,
	"name": name,
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
	"__start_line__": 4,
	"__end_line__": 4,
}

test_violation_when_neither_is_declared if {
	violations := missing_command.violations with input as _df(
		[_stage(0, null, true)],
		[_inst("RUN", "pip install -r requirements.txt", 0)],
	)
	count(violations) == 1
	some v in violations
	v.line_start == 1
}

test_no_violation_when_cmd_is_declared if {
	violations := missing_command.violations with input as _df(
		[_stage(0, null, true)],
		[_inst("CMD", "[\"python\", \"/app/main.py\"]", 0)],
	)
	count(violations) == 0
}

test_no_violation_when_entrypoint_is_declared if {
	violations := missing_command.violations with input as _df(
		[_stage(0, null, true)],
		[_inst("ENTRYPOINT", "[\"/app/start\"]", 0)],
	)
	count(violations) == 0
}

# A CMD in a builder stage does not ship, so it does not satisfy this.
test_violation_when_only_a_builder_stage_declares_one if {
	violations := missing_command.violations with input as _df(
		[_stage(0, "builder", false), _stage(1, null, true)],
		[
			_inst("CMD", "[\"npm\", \"run\", \"build\"]", 0),
			_inst("COPY", "--from=builder /out /app", 1),
		],
	)
	count(violations) == 1
}

test_no_violation_when_the_final_stage_declares_one if {
	violations := missing_command.violations with input as _df(
		[_stage(0, "builder", false), _stage(1, null, true)],
		[
			_inst("RUN", "npm run build", 0),
			_inst("CMD", "[\"node\", \"server.js\"]", 1),
		],
	)
	count(violations) == 0
}

test_reports_the_final_stage_name if {
	violations := missing_command.violations with input as _df(
		[_stage(0, "runtime", true)],
		[_inst("RUN", "true", 0)],
	)
	count(violations) == 1
	some v in violations
	v.stage_name == "runtime"
}

test_one_finding_per_dockerfile if {
	violations := missing_command.violations with input as {"dockerfiles": [
		{
			"__docker_file": "Dockerfile",
			"final_stage": 0,
			"stages": [_stage(0, null, true)],
			"instructions": [_inst("RUN", "true", 0)],
		},
		{
			"__docker_file": "api.Dockerfile",
			"final_stage": 0,
			"stages": [_stage(0, null, true)],
			"instructions": [_inst("RUN", "true", 0)],
		},
	]}
	count(violations) == 2
	count({v.file_path | some v in violations}) == 2
}
