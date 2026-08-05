package greensecops.container_docker.energy.apt_recommends_not_disabled_test

import data.greensecops.container_docker.energy.apt_recommends_not_disabled as no_recommends
import rego.v1

_df(instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [{"index": 0, "name": null, "is_final": true, "__start_line__": 1, "__end_line__": 9}],
	"instructions": instructions,
}]}

_run(value, line) := {
	"instruction": "RUN",
	"value": value,
	"flags": {},
	"stage": 0,
	"heredoc": null,
	"__start_line__": line,
	"__end_line__": line,
}

test_violation_without_the_flag if {
	violations := no_recommends.violations with input as _df([_run("apt-get update && apt-get install -y curl", 2)])
	count(violations) == 1
}

test_no_violation_with_the_flag if {
	violations := no_recommends.violations with input as _df([
		_run("apt-get update && apt-get install -y --no-install-recommends curl", 2),
	])
	count(violations) == 0
}

test_no_violation_when_set_globally_in_the_same_run if {
	violations := no_recommends.violations with input as _df([
		_run("echo 'APT::Install-Recommends \"false\";' > /etc/apt/apt.conf.d/99no-recommends && apt-get install -y curl", 2),
	])
	count(violations) == 0
}

# A global setting written earlier in the same stage covers later installs.
test_no_violation_when_set_globally_by_an_earlier_instruction if {
	violations := no_recommends.violations with input as _df([
		_run("echo 'APT::Install-Recommends \"false\";' > /etc/apt/apt.conf.d/99no-recommends", 2),
		_run("apt-get update && apt-get install -y curl", 4),
	])
	count(violations) == 0
}

# ...but one written *after* the install does not apply to it.
test_violation_when_the_global_setting_comes_later if {
	violations := no_recommends.violations with input as _df([
		_run("apt-get update && apt-get install -y curl", 2),
		_run("echo 'APT::Install-Recommends \"false\";' > /etc/apt/apt.conf.d/99no-recommends", 4),
	])
	count(violations) == 1
}

test_no_violation_for_a_non_apt_install if {
	violations := no_recommends.violations with input as _df([_run("apk add --no-cache curl", 2)])
	count(violations) == 0
}

test_no_violation_for_apt_get_update_alone if {
	violations := no_recommends.violations with input as _df([_run("apt-get update", 2)])
	count(violations) == 0
}

test_each_offending_install_is_its_own_finding if {
	violations := no_recommends.violations with input as _df([
		_run("apt-get install -y curl", 2),
		_run("apt-get install -y git", 4),
	])
	count(violations) == 2
}
