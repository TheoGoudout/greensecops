package greensecops.container_docker.security.container_runs_as_root_test

import data.greensecops.container_docker.security.container_runs_as_root
import rego.v1

# Mirrors what app.services.docker.dockerfile_parser produces: a flat ordered
# `instructions` list whose entries carry a `stage` index, plus a `stages` list
# where exactly one entry has is_final == true.

_df(stages, instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": instructions,
}]}

_stage(index, name, final) := {
	"index": index,
	"name": name,
	"is_final": final,
	"__start_line__": 1,
	"__end_line__": 9,
}

test_violation_when_no_user_instruction if {
	violations := container_runs_as_root.violations with input as _df(
		[_stage(0, null, true)],
		[{"instruction": "FROM", "value": "node:22", "stage": 0, "__start_line__": 1, "__end_line__": 1}],
	)
	count(violations) == 1
}

test_violation_when_user_is_explicitly_root if {
	violations := container_runs_as_root.violations with input as _df(
		[_stage(0, null, true)],
		[{"instruction": "USER", "value": "root", "stage": 0, "__start_line__": 3, "__end_line__": 3}],
	)
	count(violations) == 1
	some v in violations
	v.line_start == 3
}

test_violation_when_user_is_uid_zero if {
	violations := container_runs_as_root.violations with input as _df(
		[_stage(0, null, true)],
		[{"instruction": "USER", "value": "0", "stage": 0, "__start_line__": 3, "__end_line__": 3}],
	)
	count(violations) == 1
}

test_no_violation_with_unprivileged_user if {
	violations := container_runs_as_root.violations with input as _df(
		[_stage(0, null, true)],
		[{"instruction": "USER", "value": "app", "stage": 0, "__start_line__": 3, "__end_line__": 3}],
	)
	count(violations) == 0
}

# A root USER in a builder stage is fine; only the final stage ships.
test_no_violation_when_only_builder_stage_is_root if {
	violations := container_runs_as_root.violations with input as _df(
		[_stage(0, "builder", false), _stage(1, null, true)],
		[
			{"instruction": "USER", "value": "root", "stage": 0, "__start_line__": 2, "__end_line__": 2},
			{"instruction": "USER", "value": "app", "stage": 1, "__start_line__": 8, "__end_line__": 8},
		],
	)
	count(violations) == 0
}

# The last USER in the final stage wins — switching back to root re-breaks it.
test_violation_when_user_switches_back_to_root if {
	violations := container_runs_as_root.violations with input as _df(
		[_stage(0, null, true)],
		[
			{"instruction": "USER", "value": "app", "stage": 0, "__start_line__": 3, "__end_line__": 3},
			{"instruction": "USER", "value": "root", "stage": 0, "__start_line__": 5, "__end_line__": 5},
		],
	)
	count(violations) == 1
	some v in violations
	v.line_start == 5
}
