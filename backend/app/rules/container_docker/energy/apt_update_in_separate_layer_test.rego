package greensecops.container_docker.energy.apt_update_in_separate_layer_test

import data.greensecops.container_docker.energy.apt_update_in_separate_layer as separate_update
import rego.v1

_df(instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [{"index": 0, "name": null, "is_final": true, "__start_line__": 1, "__end_line__": 9}],
	"instructions": instructions,
}]}

_run(value) := {
	"instruction": "RUN",
	"value": value,
	"flags": {},
	"stage": 0,
	"heredoc": null,
	"__start_line__": 2,
	"__end_line__": 2,
}

test_violation_when_update_stands_alone if {
	violations := separate_update.violations with input as _df([
		_run("apt-get update"),
		_run("apt-get install -y curl"),
	])
	count(violations) == 1
	some v in violations
	v.line_start == 2
}

# The parser folds line continuations into one logical instruction, so a
# properly chained update+install arrives as a single value.
test_no_violation_when_update_and_install_share_a_run if {
	violations := separate_update.violations with input as _df([
		_run("apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*"),
	])
	count(violations) == 0
}

test_no_violation_for_the_bare_apt_command if {
	violations := separate_update.violations with input as _df([_run("apt update && apt install -y curl")])
	count(violations) == 0
}

test_violation_for_bare_apt_update_alone if {
	violations := separate_update.violations with input as _df([_run("apt update")])
	count(violations) == 1
}

test_no_violation_for_an_unrelated_run if {
	violations := separate_update.violations with input as _df([_run("npm ci")])
	count(violations) == 0
}

# apt-get upgrade is a different verb and not this finding.
test_no_violation_for_apt_get_upgrade if {
	violations := separate_update.violations with input as _df([_run("apt-get upgrade -y")])
	count(violations) == 0
}

test_violation_inside_a_heredoc_body if {
	violations := separate_update.violations with input as _df([{
		"instruction": "RUN",
		"value": "<<EOF",
		"flags": {},
		"stage": 0,
		"heredoc": "set -eu\napt-get update\n",
		"__start_line__": 2,
		"__end_line__": 5,
	}])
	count(violations) == 1
}

test_no_violation_when_the_heredoc_also_installs if {
	violations := separate_update.violations with input as _df([{
		"instruction": "RUN",
		"value": "<<EOF",
		"flags": {},
		"stage": 0,
		"heredoc": "set -eu\napt-get update\napt-get install -y curl\n",
		"__start_line__": 2,
		"__end_line__": 6,
	}])
	count(violations) == 0
}
