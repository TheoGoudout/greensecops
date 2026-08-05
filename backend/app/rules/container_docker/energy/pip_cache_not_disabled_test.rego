package greensecops.container_docker.energy.pip_cache_not_disabled_test

import data.greensecops.container_docker.energy.pip_cache_not_disabled
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
	violations := pip_cache_not_disabled.violations with input as _df([_run("pip install -r requirements.txt", 3)])
	count(violations) == 1
	some v in violations
	v.line_start == 3
}

test_no_violation_with_the_flag if {
	violations := pip_cache_not_disabled.violations with input as _df([_run("pip install --no-cache-dir -r requirements.txt", 3)])
	count(violations) == 0
}

test_violation_for_python_m_pip if {
	violations := pip_cache_not_disabled.violations with input as _df([_run("python -m pip install requests", 3)])
	count(violations) == 1
}

test_no_violation_when_env_disables_the_cache_earlier if {
	violations := pip_cache_not_disabled.violations with input as _df([
		{
			"instruction": "ENV",
			"value": "PIP_NO_CACHE_DIR=1",
			"flags": {},
			"stage": 0,
			"heredoc": null,
			"__start_line__": 2,
			"__end_line__": 2,
		},
		_run("pip install -r requirements.txt", 4),
	])
	count(violations) == 0
}

# A BuildKit cache mount keeps the cache out of the layer entirely, which is
# the better fix rather than a violation.
test_no_violation_with_a_buildkit_cache_mount if {
	violations := pip_cache_not_disabled.violations with input as _df([{
		"instruction": "RUN",
		"value": "pip install -r requirements.txt",
		"flags": {"mount": "type=cache,target=/root/.cache/pip"},
		"stage": 0,
		"heredoc": null,
		"__start_line__": 3,
		"__end_line__": 3,
	}])
	count(violations) == 0
}

test_no_violation_for_a_non_pip_install if {
	violations := pip_cache_not_disabled.violations with input as _df([_run("npm ci", 3)])
	count(violations) == 0
}

# `pip download` is not an install.
test_no_violation_for_pip_download if {
	violations := pip_cache_not_disabled.violations with input as _df([_run("pip download requests -d /wheels", 3)])
	count(violations) == 0
}

test_each_offending_install_is_its_own_finding if {
	violations := pip_cache_not_disabled.violations with input as _df([
		_run("pip install -r requirements.txt", 3),
		_run("pip install -r dev-requirements.txt", 5),
	])
	count(violations) == 2
}
