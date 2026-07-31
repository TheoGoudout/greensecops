package greensecops.container_docker.energy.no_multistage_build_test

import data.greensecops.container_docker.energy.no_multistage_build
import rego.v1

_stage(index, name) := {"index": index, "name": name, "is_final": true, "__start_line__": 1, "__end_line__": 9}

_inst(keyword, value, stage) := {
	"instruction": keyword,
	"value": value,
	"heredoc": null,
	"stage": stage,
	"__start_line__": 2,
	"__end_line__": 2,
}

_df(stages, instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": instructions,
}]}

test_violation_for_build_essential_in_single_stage if {
	violations := no_multistage_build.violations with input as _df(
		[_stage(0, null)],
		[_inst("RUN", "apt-get install -y build-essential", 0)],
	)
	count(violations) == 1
}

test_violation_for_jdk_in_single_stage if {
	violations := no_multistage_build.violations with input as _df(
		[_stage(0, null)],
		[_inst("RUN", "apt-get install -y openjdk-21-jdk", 0)],
	)
	count(violations) == 1
}

# The whole point of a builder stage is that installing a toolchain there is
# correct, so a multi-stage file must never fire.
test_no_violation_when_multistage if {
	violations := no_multistage_build.violations with input as _df(
		[
			{"index": 0, "name": "builder", "is_final": false, "__start_line__": 1, "__end_line__": 5},
			{"index": 1, "name": null, "is_final": true, "__start_line__": 6, "__end_line__": 9},
		],
		[_inst("RUN", "apt-get install -y build-essential", 0)],
	)
	count(violations) == 0
}

test_no_violation_without_a_toolchain if {
	violations := no_multistage_build.violations with input as _df(
		[_stage(0, null)],
		[_inst("RUN", "apt-get install -y curl ca-certificates", 0)],
	)
	count(violations) == 0
}
