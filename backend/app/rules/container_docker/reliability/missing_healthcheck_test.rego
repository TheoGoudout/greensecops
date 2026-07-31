package greensecops.container_docker.reliability.missing_healthcheck_test

import data.greensecops.container_docker.reliability.missing_healthcheck
import rego.v1

_stage(index, final) := {"index": index, "name": null, "is_final": final, "__start_line__": 1, "__end_line__": 9}

_inst(keyword, value, stage) := {
	"instruction": keyword,
	"value": value,
	"stage": stage,
	"__start_line__": 3,
	"__end_line__": 3,
}

_df(stages, instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": stages[count(stages) - 1].index,
	"stages": stages,
	"instructions": instructions,
}]}

test_violation_when_cmd_without_healthcheck if {
	violations := missing_healthcheck.violations with input as _df(
		[_stage(0, true)],
		[_inst("CMD", "[\"nginx\"]", 0)],
	)
	count(violations) == 1
}

test_no_violation_when_healthcheck_present if {
	violations := missing_healthcheck.violations with input as _df(
		[_stage(0, true)],
		[
			_inst("HEALTHCHECK", "CMD wget -qO- http://localhost/ || exit 1", 0),
			_inst("CMD", "[\"nginx\"]", 0),
		],
	)
	count(violations) == 0
}

# HEALTHCHECK NONE explicitly disables health checking, so it is not a check.
test_violation_when_healthcheck_is_none if {
	violations := missing_healthcheck.violations with input as _df(
		[_stage(0, true)],
		[
			_inst("HEALTHCHECK", "NONE", 0),
			_inst("CMD", "[\"nginx\"]", 0),
		],
	)
	count(violations) == 1
}

# A base image with no CMD/ENTRYPOINT runs nothing to check.
test_no_violation_for_a_non_runnable_image if {
	violations := missing_healthcheck.violations with input as _df(
		[_stage(0, true)],
		[_inst("RUN", "apt-get install -y curl", 0)],
	)
	count(violations) == 0
}

# A healthcheck in the builder stage does not ship.
test_violation_when_healthcheck_only_in_builder_stage if {
	violations := missing_healthcheck.violations with input as _df(
		[_stage(0, false), _stage(1, true)],
		[
			_inst("HEALTHCHECK", "CMD true", 0),
			_inst("CMD", "[\"nginx\"]", 1),
		],
	)
	count(violations) == 1
}
