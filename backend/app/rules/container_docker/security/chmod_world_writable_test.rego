package greensecops.container_docker.security.chmod_world_writable_test

import data.greensecops.container_docker.security.chmod_world_writable
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
	"__start_line__": 5,
	"__end_line__": 5,
}

test_violation_for_chmod_777 if {
	violations := chmod_world_writable.violations with input as _df([_run("mkdir /data && chmod 777 /data")])
	count(violations) == 1
	some v in violations
	v.line_start == 5
}

test_violation_for_recursive_chmod_777 if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod -R 777 /app")])
	count(violations) == 1
}

test_violation_for_leading_zero_octal if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod 0777 /app")])
	count(violations) == 1
}

# 666 grants write to other just as 777 does; matching only "777" would miss it.
test_violation_for_666 if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod 666 /var/run/app.sock")])
	count(violations) == 1
}

test_violation_for_symbolic_a_plus_w if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod a+w /data")])
	count(violations) == 1
}

test_violation_for_symbolic_o_plus_w if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod o+w /data")])
	count(violations) == 1
}

test_violation_inside_a_heredoc_body if {
	violations := chmod_world_writable.violations with input as _df([{
		"instruction": "RUN",
		"value": "<<EOF",
		"flags": {},
		"stage": 0,
		"heredoc": "mkdir -p /data\nchmod 777 /data\n",
		"__start_line__": 5,
		"__end_line__": 8,
	}])
	count(violations) == 1
}

test_no_violation_for_restrictive_modes if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod 750 /data")])
	count(violations) == 0
}

test_no_violation_for_755 if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod 755 /usr/local/bin/entrypoint.sh")])
	count(violations) == 0
}

test_no_violation_for_an_executable_bit_only if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod +x /usr/local/bin/entrypoint.sh")])
	count(violations) == 0
}

test_no_violation_for_group_write_only if {
	violations := chmod_world_writable.violations with input as _df([_run("chmod 770 /data")])
	count(violations) == 0
}

test_each_offending_instruction_is_its_own_finding if {
	violations := chmod_world_writable.violations with input as _df([
		_run("chmod 777 /a"),
		_run("chmod 755 /b"),
		_run("chmod -R 666 /c"),
	])
	count(violations) == 2
}
