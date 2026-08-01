package greensecops.container_docker.maintainability.maintainer_instruction_deprecated_test

import data.greensecops.container_docker.maintainability.maintainer_instruction_deprecated
import rego.v1

_df(instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [],
	"instructions": instructions,
}]}

_inst(keyword, value) := {
	"instruction": keyword,
	"value": value,
	"stage": 0,
	"__start_line__": 2,
	"__end_line__": 2,
}

test_violation_for_maintainer if {
	violations := maintainer_instruction_deprecated.violations with input as _df([_inst("MAINTAINER", "Platform Team <platform@example.com>")])
	count(violations) == 1
}

test_no_violation_for_label_authors if {
	violations := maintainer_instruction_deprecated.violations with input as _df([_inst("LABEL", "org.opencontainers.image.authors=\"Platform Team\"")])
	count(violations) == 0
}
