package greensecops.container_docker.security.sudo_installed_in_final_stage_test

import data.greensecops.container_docker.security.sudo_installed_in_final_stage as sudo_installed
import rego.v1

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

_run(value, stage) := {
	"instruction": "RUN",
	"value": value,
	"flags": {},
	"stage": stage,
	"heredoc": null,
	"__start_line__": 3,
	"__end_line__": 3,
}

test_violation_for_apt_get_install_sudo if {
	violations := sudo_installed.violations with input as _df(
		[_stage(0, true)],
		[_run("apt-get update && apt-get install -y sudo", 0)],
	)
	count(violations) == 1
}

test_violation_for_apk_add_sudo if {
	violations := sudo_installed.violations with input as _df(
		[_stage(0, true)],
		[_run("apk add --no-cache sudo", 0)],
	)
	count(violations) == 1
}

test_violation_for_dnf_install_sudo if {
	violations := sudo_installed.violations with input as _df(
		[_stage(0, true)],
		[_run("dnf install -y sudo", 0)],
	)
	count(violations) == 1
}

# A builder stage is discarded, sudo and all.
test_no_violation_in_a_builder_stage if {
	violations := sudo_installed.violations with input as _df(
		[_stage(0, false), _stage(1, true)],
		[
			_run("apt-get install -y sudo", 0),
			_run("apt-get install -y ca-certificates", 1),
		],
	)
	count(violations) == 0
}

test_no_violation_when_sudo_is_not_installed if {
	violations := sudo_installed.violations with input as _df(
		[_stage(0, true)],
		[_run("apt-get install -y ca-certificates curl", 0)],
	)
	count(violations) == 0
}

# The match is anchored on a package-manager verb, so a path or a message
# mentioning sudo does not fire.
test_no_violation_for_an_unrelated_mention if {
	violations := sudo_installed.violations with input as _df(
		[_stage(0, true)],
		[_run("echo 'this image needs no sudo' > /etc/motd", 0)],
	)
	count(violations) == 0
}

test_violation_inside_a_heredoc_body if {
	violations := sudo_installed.violations with input as _df(
		[_stage(0, true)],
		[{
			"instruction": "RUN",
			"value": "<<EOF",
			"flags": {},
			"stage": 0,
			"heredoc": "set -eu\napt-get update\napt-get install -y sudo\n",
			"__start_line__": 3,
			"__end_line__": 7,
		}],
	)
	count(violations) == 1
}
